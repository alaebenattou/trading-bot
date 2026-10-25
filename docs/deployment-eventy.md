# Déploiement sur eventy.click

État vérifié le 25/10/2026 : application installée, moteur importable, deux comptes migrés et authentification vérifiée, file cron configurée. Le serveur web atteint l’application (contrôle HEAD : 200, CSP et cookie Secure présents). Les serveurs Namecheap Web Hosting DNS et Google DNS renvoient maintenant 199.188.200.9 pour le domaine et son alias www ; certains caches renvoient encore l’ancien parking. Le certificat du domaine reste à activer. La mise en ligne publique n’est donc pas encore validée.

Le site utilise le compte SSH `aglcode`, sur un hébergement mutualisé CloudLinux/cPanel/LiteSpeed. Python 3.12 et Passenger servent les pages ; un processus cron séparé traite les analyses.

## Emplacements

- Code : `/home/aglctvyl/apps/trading-desk`
- Python : `/home/aglctvyl/virtualenv/apps/trading-desk/3.12/bin/python`
- Configuration privée : `/home/aglctvyl/apps/trading-desk/.env`
- Données persistantes : `/home/aglctvyl/private/trading-desk`
- Racine publique du domaine : `/home/aglctvyl/eventy.click`
- Journaux : `/home/aglctvyl/logs/trading-desk-passenger.log`, `trading-desk-worker.log`

SQLite contient les comptes et les rapports. Aucun serveur MySQL/PostgreSQL n’est nécessaire pour deux administrateurs. Le dossier de données et la configuration ne sont pas dans la racine publique. La base est conservée lors des déploiements du code. Le dossier parent `/home/aglctvyl/apps` est en mode 711 pour permettre sa traversée par LiteSpeed ; le dossier privé de données est en 700 et les fichiers `.env`, base et secret de session en 600. Les deux comptes locaux ont été migrés sous forme de hachages ; leurs mots de passe restent identiques. Le secret de session de production est distinct.

## DNS et certificat

Dans le compte Namecheap, Domain List → eventy.click → Manage → Nameservers doit utiliser **Namecheap Web Hosting DNS** (`dns1.namecheaphosting.com` et `dns2.namecheaphosting.com`). Les enregistrements suivants sont ensuite gérés dans **cPanel Zone Editor** :

| Type | Hôte | Valeur |
| --- | --- | --- |
| A | `@` | `199.188.200.9` |
| CNAME | `www` | `eventy.click` |

Ne pas modifier les enregistrements mail. Après propagation, activer/vérifier le certificat pour `eventy.click` et `www.eventy.click` via **cPanel → Namecheap SSL**. Dans « Ready for installation », cliquer sur « Install » si proposé, puis attendre le statut « Active ». Le compte SSH mutualisé ne peut pas exécuter l’outil AutoSSL réservé à root ; l’API cPanel CLI est également indisponible dans son environnement cloisonné. Voir le [guide officiel Namecheap SSL](https://www.namecheap.com/support/knowledgebase/article.aspx/9387/2218/what-is-namecheap-ssl-and-how-do-i-use-it/).

Vérifier sans ignorer les erreurs de certificat :

```bash
curl -I https://eventy.click/login
```

La redirection HTTP vers HTTPS est installée dans `.htaccess`, avec exception pour les chemins de validation de certificat. `TRADING_DESK_HTTPS=1` active les cookies Secure. Ne pas utiliser le formulaire sur une connexion dont le certificat n’est pas valide.

## File d’analyses

La crontab contient cette tâche, sans remplacer les tâches existantes :

```cron
* * * * * cd /home/aglctvyl/apps/trading-desk && /home/aglctvyl/virtualenv/apps/trading-desk/3.12/bin/python -m tradingagents.web work >> /home/aglctvyl/logs/trading-desk-worker.log 2>&1
```

Le `cd` est nécessaire : la commande charge le `.env` du dossier courant, donc la même base que Passenger. Chaque passage traite les travaux disponibles puis se termine. Un verrou empêche les chevauchements ; les analyses s’exécutent une à la fois, avec la même limite de 30 minutes et l’arrêt contrôlé des processus enfants. Le lancement peut prendre jusqu’à une minute après l’envoi d’une analyse.

Ne pas lancer `serve` simultanément : Passenger sert le site et cron gère la file.

## Clé OpenRouter

Ajouter `OPENROUTER_API_KEY` au `.env` privé sur le serveur, puis redémarrer uniquement cette application :

```bash
ssh aglcode 'cloudlinux-selector restart --json --interpreter python --app-root apps/trading-desk'
```

La tâche cron relit la configuration à chaque lancement. Aucun appel payant n’a été effectué pendant le déploiement.

## Mise à jour

1. Sauvegarder la base et la configuration privées avant une modification du schéma. Utiliser l’API de sauvegarde SQLite pour une copie cohérente si le site fonctionne.
2. Transférer le code sans `.env`, base, secret de session, mots de passe, `.git` ou environnement local.
3. Dans le dossier de l’application, réinstaller avec le Python ci-dessus : `python -m pip install '.[web]'`.
4. Redémarrer l’application avec `cloudlinux-selector restart`.
5. Vérifier HTTPS, la connexion et le traitement d’une analyse avec les identifiants du propriétaire.

La sauvegarde initiale de la racine du domaine et celle de la crontab sont dans `/home/aglctvyl/deploy-backups/`. Ne pas écraser la base de production avec une nouvelle copie locale lors d’une mise à jour.
