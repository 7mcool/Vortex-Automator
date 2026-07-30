# Configuration de l'app TikTok « Sophos Publisher »

Relevée le 30 juillet 2026, avant la resoumission. Le portail TikTok perd les
formulaires à la moindre navigation : ce relevé permet de tout ressaisir d'une
traite si nécessaire.

**App ID** : `7661819405550274581` · **Type** : Others / Individual

## URL

| Champ | Valeur |
|---|---|
| Website URL | `https://sophos.hedjav.com/` |
| Terms of Service | `https://sophos.hedjav.com/terms.html` |
| Privacy Policy | `https://sophos.hedjav.com/privacy.html` |
| Redirect URI (Login Kit) | `https://sophos.hedjav.com/callback` |

Plateforme : **Web**. Catégorie : **Education**.

## Produits et périmètres

- **Login Kit** — `user.info.basic`
- **Content Posting API** — `video.upload` (dépôt en brouillons)

`video.publish` a été **retiré** volontairement : tant que l'app n'est pas
auditée, TikTok refuse la publication directe sur un compte public, et le compte
du ministère est public. L'approche brouillons contourne cette limite sans la
forcer.

## Description courte

> Publishes sermon videos from the Sophos PropheTikos ministry to its own TikTok
> account, automatically and daily.

## Justification pour la revue

> Sophos Publisher is the internal tool of the Sophos PropheTikos Christian
> ministry. There is a single user - our own administrator - publishing our own
> sermon clips to our own TikTok account. No third-party users; no data is
> shared externally.
>
> Login Kit (user.info.basic): the administrator signs in with TikTok; we read
> only the basic profile (open id, display name) to confirm the connected
> account and show "Connected as ...".
>
> Content Posting API (video.upload): the tool sends a finished sermon clip to
> the account's own TikTok drafts via PULL_FROM_URL, so the administrator can
> review and post it from the TikTok app.

## Historique des revues

| Date | Verdict | Motif |
|---|---|---|
| 13/07/2026 | Refusée | Scopes mismatch — la vidéo de démo ne montrait pas tous les périmètres |
| 23/07/2026 | Soumise | Correctif : `video.publish` retiré, nouvelle démo en sandbox |
| 29/07/2026 | **Refusée** | Site trop mince (page d'atterrissage), politique de confidentialité et conditions jugées insuffisantes, icône absente du favicon et de l'en-tête des pages légales |
| 30/07/2026 | Corrigé | Site reconstruit : 5 pages, politiques développées, favicon et icône en en-tête |

## Ce que le relecteur exigeait, et ce qui a été fait

| Exigence | Réponse |
|---|---|
| Site complet, pas une page d'atterrissage | 5 pages avec navigation : accueil, fonctionnement, chaîne, confidentialité, conditions |
| Politique de confidentialité suffisante | 11 sections : responsable, données traitées avec origine et finalité, conservation, partage, sécurité, droits, retrait d'autorisation, mineurs, transferts |
| Conditions d'utilisation suffisantes | 11 sections : objet, qui peut l'utiliser, comptes visés, droits sur les contenus, usages interdits, règles des plateformes, responsabilité, droit applicable |
| Icône dans l'onglet du navigateur | `favicon.ico`, `favicon-32.png`, `apple-touch-icon.png` sur toutes les pages |
| Icône en haut des pages légales | Bloc en-tête avec `logo-1024.png` sur `privacy.html` et `terms.html` |

## Fichiers du site

Générés par `site/_build.py` depuis `_gabarit.py`, `_contenu.py` et `_legal.py`.
Déployés dans `/opt/vortex/site/` sur le VPS, servis par le conteneur nginx
`sophos-site` derrière Traefik.

⚠️ Ne pas supprimer `tiktokOGvJV6HD2NLIvMdIZg7fQGx0gqnowS39.txt` : c'est le
fichier de vérification de propriété du domaine.
