package controller

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	managementv1alpha1 "management.example.com/clustersize/api/v1alpha1"
)

type ClusterSizeConfigReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

const (
	OperatorVersion = "2.0.76" 
)

// --- REGOLE LOCALI (Genereranno un Role locale e popoleranno la sezione "permissions:") ---
//+kubebuilder:rbac:groups=management.example.com,resources=clustersizeconfigs,verbs=get;list;watch;create;update;patch;delete,namespace=openshift-size-monitoring
//+kubebuilder:rbac:groups=management.example.com,resources=clustersizeconfigs/status,verbs=get;update;patch,namespace=openshift-size-monitoring
//+kubebuilder:rbac:groups=management.example.com,resources=clustersizeconfigs/finalizers,verbs=update,namespace=openshift-size-monitoring
//+kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete,namespace=openshift-size-monitoring
//+kubebuilder:rbac:groups="",resources=serviceaccounts;persistentvolumeclaims;configmaps,verbs=get;list;watch;create;update;patch;delete,namespace=openshift-size-monitoring
//+kubebuilder:rbac:groups=coordination.k8s.io,resources=leases,verbs=get;list;watch;create;update;patch;delete,namespace=openshift-size-monitoring
//+kubebuilder:rbac:groups="",resources=events,verbs=create;patch,namespace=openshift-size-monitoring
//+kubebuilder:rbac:groups="",resources=secrets,verbs=get;list;watch;create;update;patch;delete,namespace=openshift-size-monitoring

// --- REGOLE GLOBALI (Genereranno un ClusterRole e popoleranno "clusterPermissions:") ---
//+kubebuilder:rbac:groups=config.openshift.io,resources=clusterversions,verbs=get;list;watch

func (r *ClusterSizeConfigReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx).WithValues("version", OperatorVersion)

	config := &managementv1alpha1.ClusterSizeConfig{}
	err := r.Get(ctx, req.NamespacedName, config)
	if err != nil {
		if errors.IsNotFound(err) {
			logger.Info("ClusterSizeConfig deleted. Commencing automated infrastructure teardown...")
			return r.teardownWorkloads(ctx, req.Namespace)
		}
		return ctrl.Result{}, err
	}

	if config.Spec.Suspend {
		logger.Info("ClusterSizeConfig reconciliation suspended. Tearing down active collection pods...")
		return r.teardownWorkloads(ctx, config.Namespace)
	}

	secret := &corev1.Secret{}
	secretKey := client.ObjectKey{Name: config.Spec.Secret, Namespace: config.Namespace}
	if err := r.Get(ctx, secretKey, secret); err != nil {
		logger.Error(err, "Failed to retrieve tracking HASH_SALT secret", "namespace", config.Namespace)
		return ctrl.Result{}, err
	}
	saltBytes := secret.Data["HASH_SALT"]
	if len(saltBytes) == 0 {
		saltBytes = []byte("SuperSecretSaltValue")
	}

	logger.Info("ClusterSizeConfig trigger detected active. Evaluating telemetry matrices...")
	
	payload, err := r.compileTelemetryPayload(ctx, string(saltBytes))
	if err != nil {
		logger.Error(err, "Failed payload compilation execution sequence")
		return ctrl.Result{}, err
	}

	return r.deployWorkloads(ctx, config, payload)
}

func (r *ClusterSizeConfigReconciler) compileTelemetryPayload(ctx context.Context, salt string) (string, error) {
	logger := log.FromContext(ctx)
	clusterID, currentVer, initialVer := "unknown", "unknown", "unknown"
	var initDateEpoch int64 = 0

	clusterVersion := &unstructured.Unstructured{}
	clusterVersion.SetGroupVersionKind(schema.GroupVersionKind{
		Group:   "config.openshift.io",
		Kind:    "ClusterVersion",
		Version: "v1",
	})

	if err := r.Get(ctx, client.ObjectKey{Name: "version"}, clusterVersion); err != nil {
		logger.Error(err, "Failed to discover ClusterVersion 'version' resource.")
	} else {
		if id, found, _ := unstructured.NestedString(clusterVersion.Object, "spec", "clusterID"); found {
			clusterID = id
		}
		if history, found, _ := unstructured.NestedSlice(clusterVersion.Object, "status", "history"); found && len(history) > 0 {
			if head, ok := history[0].(map[string]interface{}); ok {
				if ver, exists := head["version"].(string); exists {
					currentVer = ver
				}
			}
			if tail, ok := history[len(history)-1].(map[string]interface{}); ok {
				if ver, exists := tail["version"].(string); exists {
					initialVer = ver
				}
				if compTimeStr, exists := tail["completionTime"].(string); exists {
					if t, err := time.Parse(time.RFC3339, compTimeStr); err == nil {
						initDateEpoch = t.Unix()
					}
				}
			}
		}
	}

	nodes := &corev1.NodeList{}
	if err := r.List(ctx, nodes); err != nil {
		return "", err
	}

	sort.Slice(nodes.Items, func(i, j int) bool { return nodes.Items[i].Name < nodes.Items[j].Name })

	var lines []string
	lines = append(lines, fmt.Sprintf("H,%s,%d,1,2,%d,None,__CURRENT_EPOCH_TOKEN__,amd64", clusterID, len(nodes.Items), initDateEpoch))

	roleGroupMap := make(map[string]int)
	roleGroupCounter := 3

	for idx, node := range nodes.Items {
		nodeID := fmt.Sprintf("%03d", idx+1)
		var roles []string
		for k := range node.Labels {
			if strings.HasPrefix(k, "node-role.kubernetes.io/") {
				if roleName := strings.TrimPrefix(k, "node-role.kubernetes.io/"); roleName != "" {
					roles = append(roles, roleName)
				}
			}
		}
		sort.Strings(roles)
		roleString := "worker"
		if len(roles) > 0 { roleString = strings.Join(roles, "#") }

		groupID, exists := roleGroupMap[roleString]
		if !exists {
			roleGroupMap[roleString] = roleGroupCounter
			groupID = roleGroupCounter
			roleGroupCounter++
		}
		lines = append(lines, fmt.Sprintf("N,%s,%s,%d,%d,true", clusterID, nodeID, groupID, node.Status.Capacity.Cpu().Value()))
	}

	var rMappings []string
	rMappings = append(rMappings, fmt.Sprintf("1=%s", currentVer), fmt.Sprintf("2=%s", initialVer))
	
	type kv struct { Key string; Value int }
	var sortedRoles []kv
	for k, v := range roleGroupMap { sortedRoles = append(sortedRoles, kv{k, v}) }
	sort.Slice(sortedRoles, func(i, j int) bool { return sortedRoles[i].Value < sortedRoles[j].Value })
	for _, pair := range sortedRoles { rMappings = append(rMappings, fmt.Sprintf("%d=%s", pair.Value, pair.Key)) }

	rEncrypted := base64.StdEncoding.EncodeToString([]byte(fmt.Sprintf("R,%s", strings.Join(rMappings, ","))))
	lines = append(lines, fmt.Sprintf("R,%s", rEncrypted))

	payloadBody := strings.Join(lines, "\n") + "\n"
	mac := hmac.New(sha256.New, []byte(salt))
	mac.Write([]byte(payloadBody))
	return fmt.Sprintf("%sT,%s\n", payloadBody, fmt.Sprintf("%x", mac.Sum(nil))), nil
}

func (r *ClusterSizeConfigReconciler) deployWorkloads(ctx context.Context, config *managementv1alpha1.ClusterSizeConfig, payload string) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	var finalOwnerReferences []metav1.OwnerReference

	// Recupera il Deployment del manager OLM per copiarne l'OwnerReference (la CSV)
	managerDep := &appsv1.Deployment{}
	if err := r.Get(ctx, client.ObjectKey{Name: "controller-manager", Namespace: config.Namespace}, managerDep); err == nil {
		if len(managerDep.GetOwnerReferences()) > 0 {
			finalOwnerReferences = managerDep.GetOwnerReferences()
			logger.Info("OwnerReference della CSV intercettata con successo dal Deployment del manager.")
		}
	}

	// Fallback sulla CR se eseguito al di fuori di OLM o errore intercettazione
	if len(finalOwnerReferences) == 0 {
		finalOwnerReferences = []metav1.OwnerReference{
			{
				APIVersion:         config.APIVersion,
				Kind:               config.Kind,
				Name:               config.Name,
				UID:                config.UID,
				Controller:         &[]bool{true}[0],
				BlockOwnerDeletion: &[]bool{true}[0],
			},
		}
	}

	sa := &corev1.ServiceAccount{ObjectMeta: metav1.ObjectMeta{Name: "clustersize-sa", Namespace: config.Namespace, OwnerReferences: finalOwnerReferences}}
	if err := r.Create(ctx, sa); err != nil && !errors.IsAlreadyExists(err) { return ctrl.Result{}, err }

	pvc := &corev1.PersistentVolumeClaim{
		ObjectMeta: metav1.ObjectMeta{Name: "clustersize-log-pvc", Namespace: config.Namespace, OwnerReferences: finalOwnerReferences},
		Spec: corev1.PersistentVolumeClaimSpec{
			AccessModes: []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce},
			Resources: corev1.ResourceRequirements{Requests: corev1.ResourceList{corev1.ResourceStorage: resource.MustParse("1Gi")}},
		},
	}
	if err := r.Create(ctx, pvc); err != nil && !errors.IsAlreadyExists(err) { return ctrl.Result{}, err }

	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{Name: "clustersize-payload-cm", Namespace: config.Namespace, OwnerReferences: finalOwnerReferences},
		Data:       map[string]string{"payload.txt": payload},
	}
	existingCM := &corev1.ConfigMap{}
	if err := r.Get(ctx, client.ObjectKey{Name: "clustersize-payload-cm", Namespace: config.Namespace}, existingCM); err != nil {
		if errors.IsNotFound(err) { _ = r.Create(ctx, cm) } else { return ctrl.Result{}, err }
	} else {
		existingCM.Data = cm.Data
		existingCM.OwnerReferences = finalOwnerReferences
		_ = r.Update(ctx, existingCM)
	}

	maxSizeBytes := config.Spec.LogMaxSizeBytes
	if maxSizeBytes == 0 { maxSizeBytes = 10485760 }
	maxRotations := config.Spec.LogMaxRotations
	if maxRotations == 0 { maxRotations = 5 }
	payloadHash := fmt.Sprintf("%x", sha256.Sum256([]byte(payload)))

	replicas := int32(1)
	dep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{Name: "clustersize", Namespace: config.Namespace, OwnerReferences: finalOwnerReferences},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{MatchLabels: map[string]string{"app": "clustersize"}},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: map[string]string{"app": "clustersize"},
					Annotations: map[string]string{"management.example.com/payload-hash": payloadHash},
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: "clustersize-sa",
					Containers: []corev1.Container{{
						Name:    "collector",
						Image:    "registry.redhat.io/openshift4/ose-cli:latest",
						Command: []string{"/bin/bash", "-c"},
						Args: []string{
							`LOG_FILE="/var/log/container/clustersize"
							SEQ_FILE="/var/log/container/.seq_counter"
							if [ -f "${SEQ_FILE}" ]; then COUNTER=$(cat "${SEQ_FILE}"); else COUNTER=0; fi
							while true; do
								LIVE_EPOCH=$(date +%s)
								sed "s/__CURRENT_EPOCH_TOKEN__/${LIVE_EPOCH}/g" /tmp/manifest/payload.txt > /tmp/live_payload.txt
								if [ -f "${LOG_FILE}" ]; then
									CURRENT_SIZE=$(stat -c%s "${LOG_FILE}" 2>/dev/null || echo 0)
									if [ ${CURRENT_SIZE} -ge ${CFG_MAX_SIZE} ]; then
										rm -f "${LOG_FILE}.${CFG_MAX_ROTS}"
										for ((i=CFG_MAX_ROTS-1; i>=1; i--)); do
											if [ -f "${LOG_FILE}.${i}" ]; then mv "${LOG_FILE}.${i}" "${LOG_FILE}.$((i+1))"; fi
										done
										mv "${LOG_FILE}" "${LOG_FILE}.1" && touch "${LOG_FILE}"
									fi
								fi
								cat /tmp/live_payload.txt >> "${LOG_FILE}"
								MSG_ID=$(printf "%012d" ${COUNTER})
								if [ ${COUNTER} -ge 999999999999 ]; then COUNTER=0; else COUNTER=$((COUNTER + 1)); fi
								echo ${COUNTER} > "${SEQ_FILE}"
								HEADER_LINE=$(grep "^H," /tmp/live_payload.txt)
								ROLE_LINE=$(grep "^R," /tmp/live_payload.txt)
								TRAILER_LINE=$(grep "^T," /tmp/live_payload.txt)
								grep "^N," /tmp/live_payload.txt > /tmp/nodes_only.txt
								TOTAL_NODES=$(wc -l < /tmp/nodes_only.txt)
								NODES_PER_FRAME=80
								TOTAL_FRAMES=$(( (TOTAL_NODES + NODES_PER_FRAME - 1) / NODES_PER_FRAME ))
								if [ ${TOTAL_FRAMES} -eq 0 ]; then TOTAL_FRAMES=1; fi
								CURRENT_FRAME=1
								for ((s=1; s<=TOTAL_NODES; s+=NODES_PER_FRAME)); do
									sed -n "${s},$((s + NODES_PER_FRAME - 1))p" /tmp/nodes_only.txt > /tmp/chunk_nodes.txt
									{ echo "${HEADER_LINE}"; cat /tmp/chunk_nodes.txt; echo "${ROLE_LINE}"; echo "${TRAILER_LINE}"; } > /tmp/frame_payload.txt
									gzip -c /tmp/frame_payload.txt > /tmp/frame_payload.gz
									STR_FRAME_NUM=$(printf "%06d" ${CURRENT_FRAME})
									STR_TOTAL_FRAMES=$(printf "%06d" ${TOTAL_FRAMES})
									echo -n "${MSG_ID},${STR_FRAME_NUM},${STR_TOTAL_FRAMES}|" > /tmp/net_packet.bin
									cat /tmp/frame_payload.gz >> /tmp/net_packet.bin
									cat /tmp/net_packet.bin > /dev/udp/${REMOTE_IP}/${REMOTE_UDP_PORT}
									CURRENT_FRAME=$((CURRENT_FRAME + 1))
								done
								sleep 30
							done`,
						},
						Env: []corev1.EnvVar{
							{Name: "REMOTE_IP", Value: config.Spec.RemoteIp},
							{Name: "REMOTE_UDP_PORT", Value: strconv.Itoa(config.Spec.RemoteUdpPort)},
							{Name: "CFG_MAX_SIZE", Value: strconv.FormatInt(int64(maxSizeBytes), 10)},
							{Name: "CFG_MAX_ROTS", Value: strconv.Itoa(int(maxRotations))},
						},
						VolumeMounts: []corev1.VolumeMount{{Name: "log-vol", MountPath: "/var/log/container"}, {Name: "payload-vol", MountPath: "/tmp/manifest"}},
					}},
					Volumes: []corev1.Volume{
						{Name: "log-vol", VolumeSource: corev1.VolumeSource{PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{ClaimName: "clustersize-log-pvc"}}},
						{Name: "payload-vol", VolumeSource: corev1.VolumeSource{ConfigMap: &corev1.ConfigMapVolumeSource{LocalObjectReference: corev1.LocalObjectReference{Name: "clustersize-payload-cm"}}}},
					},
				},
			},
		},
	}

	existingDep := &appsv1.Deployment{}
	if err := r.Get(ctx, client.ObjectKey{Name: "clustersize", Namespace: config.Namespace}, existingDep); err != nil {
		if errors.IsNotFound(err) { _ = r.Create(ctx, dep) } else { return ctrl.Result{}, err }
	} else {
		existingDep.Spec = dep.Spec
		existingDep.OwnerReferences = finalOwnerReferences
		_ = r.Update(ctx, existingDep)
	}

	return ctrl.Result{}, nil
}

func (r *ClusterSizeConfigReconciler) teardownWorkloads(ctx context.Context, namespace string) (ctrl.Result, error) {
	objectsToDelete := []client.Object{
		&appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: "clustersize", Namespace: namespace}},
		&corev1.PersistentVolumeClaim{ObjectMeta: metav1.ObjectMeta{Name: "clustersize-log-pvc", Namespace: namespace}},
		&corev1.ConfigMap{ObjectMeta: metav1.ObjectMeta{Name: "clustersize-payload-cm", Namespace: namespace}},
		&corev1.ServiceAccount{ObjectMeta: metav1.ObjectMeta{Name: "clustersize-sa", Namespace: namespace}},
	}
	for _, obj := range objectsToDelete { _ = r.Delete(ctx, obj) }
	return ctrl.Result{}, nil
}

func (r *ClusterSizeConfigReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&managementv1alpha1.ClusterSizeConfig{}).
		Owns(&appsv1.Deployment{}).
		Complete(r)
}
