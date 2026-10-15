# Validation

## Automatisation locale et CI

```sh
python3 -m unittest discover -s tests -v
docker compose --env-file .env.example config --quiet
python3 tests/integration.py
python3 tests/integration.py --image monolithoid/streamevent-relay:VOTRE_TAG
```

Le test crée un MediaMTX dédié, une source FFmpeg et un lecteur enregistrant le
programme. Avec `--image`, le contrôleur tourne dans l’image candidate, avec son
UID non root, en lecture seule. Ports loopback 19350/18554, identifiants factices,
aucun YouTube. Durée : quelques minutes ; ne pas lancer deux instances simultanées.

La capture utilise **une seule connexion de lecture RTMP**, sans reconnexion
automatique. Cela contrôle la sortie dans le protocole de diffusion, sans ajouter
une conversion RTSP côté capture. Le lecteur et l’encodeur doivent rester actifs
pendant tous les changements de source.

| Scénario | Critère |
| --- | --- |
| Sans téléphone | Attente, H.264 et AAC |
| Arrivée/départ/reconnexion | Pixels rouges du match et pixels bleus de l’attente |
| Source connectée mais sans paquets | Attente après SIGSTOP, reprise après SIGCONT |
| Vidéo sans audio | Encodeur conservé, sortie AAC silencieuse |
| Trois cycles | Un seul `output_started`, lecteur toujours actif |
| Timestamps | DTS strictement croissants ; écart vidéo <80 ms et audio <50 ms |
| Contenu audio | Tonalité décodée et intervalles silencieux |
| Overlay PNG | Texte blanc de l’overlay visible sur la première image d’attente |
| Récepteur indisponible puis rétabli | Nouvelle connexion automatique, deux codecs reçus |
| Contrôleur relancé | Retour automatique à l’attente |

Les fichiers sont conservés dans `test-results/` ; les ressources Docker sont
nettoyées. La CI teste le conteneur avant publication et joint les résultats
comme artefact temporaire. La résolution synthétique est 320×180/30 FPS : ce
test ne valide pas la puissance du VPS en 1080p ni tous les blackholes réseau.

Pour refaire le scénario à la résolution cible (sur une machine suffisamment puissante) :

```sh
TEST_WIDTH=1920 TEST_HEIGHT=1080 TEST_BITRATE=6000k TEST_PRESET=veryfast TEST_THREADS=4 \
  python3 tests/integration.py --image monolithoid/streamevent-relay:VOTRE_TAG
```

Le test limite le relais à 1,5 Go, 128 processus/threads et au plus cinq CPU,
en s’adaptant au nombre de CPU du démon Docker. `TEST_CPUS` permet de choisir un
quota plus bas. Le VPS de production doit disposer du quota configuré dans Compose.

## Essais terrain avant un match public

1. Créer un événement YouTube non répertorié et désactiver son arrêt automatique.
2. Vérifier l’attente initiale, le silence, puis le téléphone, le cadrage et le logo.
3. Filmer un claquement de mains pour mesurer le décalage audio/vidéo ; refaire à
   30 minutes et deux heures. Cible initiale conseillée : moins de 250 ms sans
   dérive croissante. Ce seuil est à mesurer, il n’est pas garanti par le test local.
4. Arrêter/reprendre la publication dix fois ; vérifier le même événement YouTube,
   un seul `output_started`, le retour de l’audio et l’absence de gel prolongé.
5. Couper les données mobiles pendant 5, 15 puis 60 secondes ; relever les délais
   d’attente et de reprise. Vérifier le comportement de l’application Android.
6. Publier une vidéo sans piste audio puis reconnecter une source avec audio.
7. En préproduction, arrêter/rétablir uniquement le récepteur ; vérifier backoff
   et reprise. Ne pas couper le réseau global d’un VPS hébergeant d’autres services.
8. Redémarrer le conteneur relais ; une nouvelle connexion est attendue. Vérifier
   séparément si YouTube a conservé l’événement.
9. Surveiller deux heures avec `docker stats` et Coolify : mémoire stable, marge
   CPU, absence de `scheduler_overrun`, saturation et redémarrages d’encodeur.
10. Refaire en 720p si nécessaire et avec les PNG définitifs.

Consigner digest des images, modèle téléphone/application, réseau, réglages,
délais de basculement, synchronisation audio/vidéo, CPU/RAM et statut YouTube.

## Diagnostic

- `input_unavailable` est normal sans téléphone ; sinon vérifier URL, identifiants,
  port OVH, chemin `live`, codec et réseau Docker.
- `output_lost` : vérifier clé/URL YouTube, événement, réseau et ressources.
- `scheduler_overrun` : réduire résolution/cadence ou utiliser un preset plus rapide.
- PNG illisible : vérifier existence, permissions, chemins internes `/assets` et format.
- Événement clôturé : reprendre/créer l’événement dans Studio ; une relance de
  FFmpeg ne peut pas annuler une clôture YouTube.

Garder les logs de test en cas d’échec. Ne pas publier des logs ou une inspection
Docker de production sans vérifier l’absence de secrets.
