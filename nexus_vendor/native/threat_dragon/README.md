# OWASP Threat Dragon (Node.js/Express)
**Source :** threat-dragon.zip → threat-dragon-main/td.server/src/
**Language :** JavaScript (Node.js 18+)
**Démarrage :** `docker run -p 3000:3000 --env-file .env owasp/threat-dragon:latest`

## Fichiers JS extraits

| Fichier | Rôle |
|---------|------|
| `controllers/threatmodelcontroller.js` | CRUD modèles de menace (via GitHub API) |
| `controllers/templateController.js` | Gestion des templates de modèles |
| `controllers/auth.js` | OAuth GitHub/GitLab/Bitbucket : login, logout, callback |
| `helpers/encryption.helper.js` | AES-256-GCM : `encrypt(plaintext, key)`, `decrypt(obj, key)` |
| `helpers/jwt.helper.js` | JWT sessions : `createJWT(user)`, `verifyJWT(token)` |
| `repositories/github.js` | Client GitHub API : CRUD fichiers dans un repo |
| `repositories/gitlab.js` | Client GitLab API |
| `repositories/bitbucket.js` | Client Bitbucket API |
| `middlewares/auth.middleware.js` | Middleware d'authentification Express |
| `config.js` | Configuration depuis variables d'environnement |

## Endpoints REST (controllers/threatmodelcontroller.js)

```javascript
// CRUD modèles
GET    /api/threatmodel/:org/:repo/:branch/all       → listModels(req, res)
GET    /api/threatmodel/:org/:repo/:branch/:model    → getModel(req, res)
POST   /api/threatmodel/:org/:repo/:branch/:model    → saveModel(req, res)
DELETE /api/threatmodel/:org/:repo/:branch/:model    → deleteModel(req, res)

// Templates
GET    /api/threatmodel/templates                    → listTemplates(req, res)
GET    /api/threatmodel/templates/:name              → getTemplate(req, res)
POST   /api/threatmodel/templates                    → createTemplate(req, res)

// Auth
GET    /api/oauth/token/:provider                    → login(req, res)
GET    /api/oauth/return/:provider                   → callback(req, res)
GET    /api/oauth/logout                             → logout(req, res)
```

## Fonctions JS clés

```javascript
// helpers/encryption.helper.js
function encrypt(plaintext, key) → { iv, ciphertext, tag }
    // AES-256-GCM. key = ENCRYPTION_KEYS_VALUE (32 chars min)
function decrypt({ iv, ciphertext, tag }, key) → plaintext

// helpers/jwt.helper.js
function createJWT(user) → string    // JWT signé avec ENCRYPTION_JWT_SIGNING_KEY
function verifyJWT(token) → user     // Vérifie et décode le token
```
