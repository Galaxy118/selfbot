# Selfbot Manager

Selfbot Manager est une interface de gestion web et une API (FastAPI) performante conçue pour orchestrer de multiples bots Discord (Selfbots). 

L'architecture est entièrement **asynchrone**, offrant un tableau de bord au rendu premium (Glassmorphism), mis à jour en temps réel (SSE), et capable de gérer des centaines de tokens simultanément sans ralentissements.

## 🚀 Fonctionnalités
- **Dashboard Premium** : Interface en Vanilla JS + CSS avec design Glassmorphism (performances visuelles maximales).
- **Performances Backend Ultimes** : Utilisation de `aiosqlite` (base de données asynchrone avec mode WAL) pour éviter tout blocage du serveur.
- **Temps Réel** : Les changements de statut des bots remontent à l'interface instantanément grâce au **Server-Sent Events (SSE)**. Plus besoin de recharger la page.
- **Gestion Multi-Utilisateurs** : Authentification Discord OAuth2 avec panel d'administration pour les propriétaires (gestion des accès).
- **Fonctionnalités Bot** : Choix des salons vocaux, mute/deaf automatiques, configuration des statuts (idle, online, dnd, invisible) et rotation automatique des statuts.

## 📂 Architecture du Projet
Le projet est entièrement modulaire ("scalable") :
- `main.py` : Le point d'entrée de l'application FastAPI.
- `app/` : 
  - `database.py` : Initialisation et requêtes asynchrones vers SQLite.
  - `config.py` : Chargement des variables (`.env`) et chiffrement des tokens.
  - `discord_manager.py` : L'orchestrateur du système (gestion en arrière-plan des WebSockets de l'API Discord).
  - `routers/` : Les différentes routes de l'API (`auth.py`, `tokens.py`, `settings.py`, `frontend.py`).
- `static/` : Les ressources statiques de l'interface utilisateur.

## 🛠️ Installation et Déploiement

### 1. Prérequis
Assurez-vous d'avoir installé **Python 3.9+**.

### 2. Installation des dépendances
Il est fortement recommandé d'utiliser un environnement virtuel :
```bash
# Créer et activer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

### 3. Configuration (.env)
Créez un fichier `.env` à la racine de ce projet avec vos identifiants d'application Discord :
```env
CLIENT_ID=votre_client_id_discord
CLIENT_SECRET=votre_client_secret_discord
REDIRECT_URI=http://localhost:8001/auth/callback
OWNER_IDS=id_discord_admin_1,id_discord_admin_2

# Optionnel (fortement recommandé en production pour ne pas déconnecter les users au redémarrage) :
# ENCRYPTION_KEY=une_cle_fernet_generee
# SESSION_SECRET=un_code_secret_tres_long
```
*(⚠️ Si vous déployez sur internet (ex: Cloudflare), remplacez `localhost:8001` par votre domaine public dans `REDIRECT_URI`).*

### 4. Démarrage Local (Sans Docker)
Lancez l'application avec Uvicorn :
```bash
uvicorn main:app --host 0.0.0.0 --port 8001
```
L'interface sera alors accessible sur [http://localhost:8001](http://localhost:8001).

## 🐳 Déploiement en Production (Docker + Cloudflare)

Puisque tu utilises **Cloudflare Tunnels**, la façon la plus propre et robuste de déployer l'application pour qu'elle tourne 24/7 est d'utiliser **Docker**.

### Étape 1 : Lancer le conteneur Docker
Assure-toi d'avoir Docker installé sur ton serveur ou ta machine. Depuis la racine du projet `selfbot`, exécute simplement :
```bash
docker-compose up -d --build
```
*Le système va télécharger l'environnement Python, installer les dépendances et lancer l'application en tâche de fond de façon complètement isolée. Ta base de données est sauvegardée en sécurité dans le dossier `data/`.*

### Étape 2 : Relier à Cloudflare Tunnels
1. Dans le tableau de bord Zero Trust de Cloudflare, crée/modifie un tunnel.
2. Ajoute un *Public Hostname* (ex: `selfbot.tondomaine.com`).
3. Fais pointer ce nom de domaine vers le service local : `http://localhost:8001`.

### Étape 3 : Mise à jour Discord OAuth2
C'est l'étape la plus oubliée ! 
1. Retourne sur le [Portail Développeur Discord](https://discord.com/developers/applications).
2. Dans la section **OAuth2**, ajoute ton nouveau domaine aux redirections (ex: `https://selfbot.tondomaine.com/auth/callback`).
3. Modifie la variable `REDIRECT_URI` dans ton fichier `.env` pour qu'elle corresponde exactement à cette URL.
4. Si tu as modifié ton `.env`, relance le docker avec : `docker-compose restart`.

---
*Propulsé par FastAPI, aiosqlite, Docker et Vanilla JS pour des performances brutes.*
