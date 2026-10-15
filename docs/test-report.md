# Résultats locaux du 15 octobre 2026

Ces résultats décrivent l’environnement de développement, pas le VPS OVH ni
YouTube. Aucun secret ni événement YouTube n’a été utilisé.

## Environnement

- Docker Engine 28.4, Compose 2.40, Linux amd64 ; trois CPU disponibles au démon.
- MediaMTX officiel 1.15.3.
- Image du relais construite localement à partir de Python 3.13.12 slim bookworm.
- FFmpeg Debian 5.1.9 dans l’image ; FFmpeg 7.1.5 sur l’hôte pour le générateur/lecteur.
- Relais en lecture seule, UID 10001, aucune capacité Linux, tmpfs 32 Mo,
  mémoire limitée à 1,5 Go, 128 processus/threads et quota de trois CPU.

## Vérifications effectuées

- Cinq tests unitaires : sélection/préchauffage, données périmées, absence d’audio,
  lectures partielles de pipe, validation de configuration et masquage des secrets.
- Validation du Compose de production avec `config --quiet`.
- Démarrage du YAML MediaMTX de production avec les comptes injectés par Compose.
- Construction effective du Dockerfile et fonctionnement sans root.
- Scénario complet d’intégration sur FFmpeg hôte, puis dans l’image du relais.
- Sortie 320×180/30 et sortie 1920×1080/30, 6 Mbit/s, preset veryfast, quatre
  threads d’encodage pour le scénario 1080p.
- Attente initiale, trois cycles de publication, interruption des paquets par
  SIGSTOP/SIGCONT, source sans audio, panne/reprise du récepteur et redémarrage.
- Connexion de lecture anonyme refusée par MediaMTX.
- Pendant les transitions de source : même processus d’encodage et même connexion
  de lecture, sans mécanisme de reconnexion du lecteur.
- Analyse des pixels décodés : alternance attente/match, présence de l’overlay PNG.
- Analyse audio décodée : tonalité sur les sources avec audio, silence au milieu
  du match vidéo seul, puis retour de la tonalité au cycle suivant.

Sur l’enregistrement 1080p, les DTS vidéo/audio sont strictement croissants.
Écarts maximaux observés : **34 ms vidéo**, **22 ms audio**. Aucun redémarrage de
l’encodeur pendant les changements de source. La panne du récepteur ouvre,
comme prévu, une nouvelle connexion après temporisation.

Un relevé ponctuel pendant le scénario 1080p indiquait environ **181 Mio** et
**31 processus/threads**, avec un healthcheck valide. Ce n’est pas une moyenne
ni une mesure de capacité. La source rouge est synthétique en 320×180, ensuite
redimensionnée ; elle est beaucoup plus facile à encoder qu’un match réel et
ne mesure pas le coût du décodage d’un téléphone 1080p.

## Portée et suite

Le test initial utilisant une capture RTSP avait détecté une anomalie de
timestamps et l’absence de paquets AAC dans la capture. La validation du
programme utilise donc une lecture RTMP, correspondant au transport de sortie,
et analyse réellement les paquets et le son ; la réception du téléphone reste
en RTSP et l’audio de bout en bout a été vérifié.

Les essais ont aussi révélé un faux log de dépassement d’horloge pendant
l’attente volontaire de fermeture d’une sortie en panne. Le contrôleur remet
désormais son échéance à jour après cette fermeture ; la sortie était déjà coupée.

La publication distante Docker Hub, le téléchargement depuis Coolify, la connexion
RTMPS réelle, le maintien d’un événement YouTube, les téléphones et la
synchronisation labiale sur plusieurs heures restent à valider séparément
avec [la procédure terrain](validation.md). Le workflow est prêt à construire,
tester et publier lors du premier push autorisé sur GitHub.

## Entrée RTMPS via Traefik

L’entrée de production utilise désormais Traefik pour terminer TLS, puis RTMP
sur Docker vers MediaMTX. MediaMTX ne monte aucun certificat et ne publie aucun
port hôte. Le test `tests/rtmps.py` couvre cette architecture avec un certificat
temporaire : publication authentifiée réussie, certificat vérifié, mauvais nom
d’hôte rejeté et absence de port hôte MediaMTX confirmée. Les cinq tests unitaires
passent également. Le proxy isolé utilise le fournisseur de fichiers avec les
valeurs des labels TCP de production ; la découverte Docker de Coolify, le
certificat public, ACME et le téléphone restent à vérifier sur le VPS. Le premier essai de terminaison TLS directement dans MediaMTX a été
remplacé pour correspondre au déploiement Coolify.

Le contrôle des comptes a révélé que l’ancienne variable `MTX_AUTHINTERNALUSERS`
contenant du JSON était ignorée par MediaMTX 1.15.3. Le Compose conserve la
correction avec les variables indexées `MTX_AUTHINTERNALUSERS_0_USER`, etc.
