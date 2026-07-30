"""Politique de confidentialite et conditions d'utilisation.

Le relecteur TikTok a juge les deux precedentes « insuffisantes » : elles
tenaient en quelques lignes. Ces versions couvrent ce qu'une revue attend —
qui traite, quelles donnees, pourquoi, combien de temps, avec qui, quels
droits, et comment nous joindre.
"""

CONTACT = "hedjav@gmail.com"

PRIVACY = """
<p class="chapo">Sophos Publisher est un outil interne du ministère Sophos
PropheTikos. Cette politique décrit précisément quelles données il manipule,
pourquoi, et pendant combien de temps.</p>

<h2>1. Qui est responsable</h2>
<p>Le responsable du traitement est le ministère <strong>Sophos
PropheTikos</strong>, établi à Cotonou (Bénin). Pour toute question relative à
cette politique ou à l'exercice de vos droits :
<a href="mailto:%(contact)s">%(contact)s</a>.</p>

<h2>2. À qui s'adresse cet outil</h2>
<p>Sophos Publisher n'est pas un service ouvert au public. Il est utilisé
exclusivement par les responsables du ministère, pour publier sur les comptes du
ministère. Il n'existe aucune inscription, aucun compte utilisateur, et aucun
moyen pour un tiers de connecter son propre compte.</p>

<h2>3. Données que nous traitons</h2>
<table>
  <tr><th>Donnée</th><th>Origine</th><th>Pourquoi</th></tr>
  <tr><td>Nom d'affichage du compte TikTok connecté</td>
      <td>API TikTok, périmètre <code>user.info.basic</code></td>
      <td>Vérifier à l'écran que le dépôt visera bien le compte du ministère.</td></tr>
  <tr><td>Jeton d'accès et jeton de rafraîchissement TikTok</td>
      <td>Procédure d'autorisation TikTok</td>
      <td>Déposer les extraits dans les brouillons du compte.</td></tr>
  <tr><td>Fichiers vidéo des extraits</td>
      <td>Enregistrements du ministère et des ministères partenaires</td>
      <td>Constituer les extraits publiés.</td></tr>
  <tr><td>Titres, descriptions, transcriptions</td>
      <td>Produits à partir des enregistrements</td>
      <td>Accompagner chaque extrait.</td></tr>
</table>

<h3>Ce que nous ne traitons pas</h3>
<ul>
  <li>Aucune donnée sur les personnes qui regardent nos vidéos : ni identifiant,
  ni adresse, ni comportement de navigation.</li>
  <li>Aucun cookie sur ce site. Il ne comporte ni traceur, ni mesure d'audience,
  ni régie publicitaire.</li>
  <li>Aucune donnée sensible, aucun mot de passe. Nous ne demandons jamais le
  mot de passe d'un compte : l'autorisation passe uniquement par la procédure
  officielle de TikTok.</li>
  <li>Aucune donnée provenant du compte d'un tiers.</li>
</ul>

<h2>4. Conservation</h2>
<ul>
  <li><strong>Jetons TikTok</strong> — conservés le temps que l'autorisation
  reste active, dans un fichier à accès restreint sur notre serveur. Ils sont
  détruits dès la révocation de l'autorisation ou l'arrêt de l'outil.</li>
  <li><strong>Nom d'affichage</strong> — affiché pendant la session de travail,
  non enregistré durablement.</li>
  <li><strong>Fichiers vidéo intermédiaires</strong> — effacés dès que l'extrait
  est en ligne, généralement sous quelques heures.</li>
  <li><strong>Extraits publiés</strong> — conservés tant qu'ils restent en ligne
  sur nos comptes.</li>
</ul>

<h2>5. Partage avec des tiers</h2>
<p>Nous ne vendons ni ne louons aucune donnée. Les seuls destinataires sont les
plateformes vers lesquelles nous publions, et un service d'intelligence
artificielle :</p>
<ul>
  <li><strong>TikTok</strong> — reçoit l'extrait vidéo et son titre, pour le
  dépôt en brouillon.</li>
  <li><strong>YouTube, Facebook, Instagram</strong> — reçoivent les extraits
  publiés sur nos comptes.</li>
  <li><strong>DeepSeek</strong> — reçoit la <em>transcription textuelle</em> des
  prédications pour proposer titres et découpages. Aucun jeton, aucune donnée de
  compte, aucun fichier vidéo ne lui est transmis.</li>
</ul>

<h2>6. Sécurité</h2>
<ul>
  <li>Les jetons et clés vivent dans des fichiers à permissions restreintes, sur
  un serveur auquel seuls les responsables du ministère accèdent par clé SSH.</li>
  <li>Aucun secret n'est publié dans le code source du projet.</li>
  <li>Les échanges avec les plateformes se font en HTTPS.</li>
  <li>L'autorisation TikTok est renouvelée par la procédure officielle ; elle
  n'est jamais contournée.</li>
</ul>

<h2>7. Vos droits</h2>
<p>Vous pouvez nous demander l'accès aux données vous concernant, leur
rectification, leur effacement, ou vous opposer à leur traitement. Écrivez à
<a href="mailto:%(contact)s">%(contact)s</a> ; nous répondons sous trente jours.</p>
<p>Si un extrait vous concerne et que vous souhaitez son retrait, indiquez-nous
le lien : nous le retirons le temps d'examiner la demande.</p>

<h2>8. Retirer l'autorisation TikTok</h2>
<p>Le ministère peut retirer à tout moment l'accès accordé à Sophos Publisher,
depuis les réglages de sécurité de son compte TikTok. Le retrait rend les jetons
inutilisables immédiatement ; nous les supprimons de notre serveur.</p>

<h2>9. Enfants</h2>
<p>Cet outil est réservé aux responsables du ministère, tous majeurs. Nous ne
collectons sciemment aucune donnée concernant un mineur.</p>

<h2>10. Transferts hors du Bénin</h2>
<p>Nos serveurs sont hébergés en Europe. Les plateformes destinataires (TikTok,
YouTube, Meta) traitent les données selon leurs propres politiques, dans les pays
où elles opèrent.</p>

<h2>11. Modifications</h2>
<p>Toute modification de cette politique sera publiée sur cette page, avec sa
date de mise à jour. Les changements substantiels seront signalés en tête de
page.</p>
""" % {"contact": CONTACT}


TERMS = """
<p class="chapo">Ces conditions encadrent l'usage de Sophos Publisher, outil
interne du ministère Sophos PropheTikos.</p>

<h2>1. Objet</h2>
<p>Sophos Publisher prépare des extraits de prédications et les dépose sur les
comptes du ministère Sophos PropheTikos. Il s'agit d'un outil interne : il n'est
ni vendu, ni loué, ni mis à disposition du public.</p>

<h2>2. Qui peut l'utiliser</h2>
<p>Seuls les responsables du ministère, expressément autorisés. Aucune
inscription n'est ouverte. L'outil ne comporte aucun mécanisme permettant à une
personne extérieure de connecter un compte ou de déclencher une publication.</p>

<h2>3. Comptes visés</h2>
<p>L'outil publie exclusivement sur les comptes du ministère. Il n'agit jamais
au nom d'un tiers, ne publie jamais sur le compte d'autrui, et ne propose aucun
service de publication à des tiers.</p>

<h2>4. Contenus et droits</h2>
<ul>
  <li>Les prédications proviennent des enregistrements du ministère ou de
  ministères partenaires ayant donné leur accord.</li>
  <li>Chaque extrait crédite le prédicateur et son église, et renvoie à la vidéo
  d'origine.</li>
  <li>Un prédicateur n'est nommé que si son identité est établie avec certitude.
  Dans le doute, l'extrait paraît sans attribution.</li>
  <li>Toute réclamation relative aux droits sur un contenu peut être adressée à
  <a href="mailto:%(contact)s">%(contact)s</a>. Le contenu contesté est retiré le
  temps de l'examen.</li>
</ul>

<h2>5. Usages interdits</h2>
<p>Il est exclu d'employer cet outil pour :</p>
<ul>
  <li>publier sur un compte qui n'appartient pas au ministère ;</li>
  <li>diffuser un contenu haineux, trompeur, violent ou illicite ;</li>
  <li>solliciter des paiements : les passages appelant aux dons ou contenant des
  coordonnées de paiement sont écartés automatiquement des extraits ;</li>
  <li>contourner les règles des plateformes destinataires, ou automatiser une
  interaction que celles-ci n'autorisent pas.</li>
</ul>

<h2>6. Règles des plateformes</h2>
<p>L'usage de l'outil reste soumis aux conditions des plateformes concernées,
notamment les <a href="https://www.tiktok.com/legal/terms-of-service"
rel="noopener">conditions de TikTok</a> et ses règles pour les développeurs. En
cas de contradiction, les règles de la plateforme prévalent.</p>

<h2>7. Interruptions</h2>
<p>L'outil peut être arrêté, modifié ou indisponible à tout moment, notamment
lors d'une maintenance ou d'une panne de nos serveurs. Aucune continuité de
service n'est garantie, l'usage étant strictement interne.</p>

<h2>8. Responsabilité</h2>
<p>L'outil est fourni en l'état, pour l'usage propre du ministère. Le ministère
demeure responsable des contenus qu'il publie sur ses comptes. Aucune garantie
n'est donnée quant à l'audience, la portée ou la disponibilité des contenus sur
les plateformes.</p>

<h2>9. Données personnelles</h2>
<p>Le traitement des données est décrit dans notre
<a href="privacy.html">politique de confidentialité</a>, qui fait partie
intégrante de ces conditions.</p>

<h2>10. Modifications</h2>
<p>Ces conditions peuvent être modifiées. La version en vigueur est celle publiée
sur cette page, avec sa date de mise à jour.</p>

<h2>11. Droit applicable et contact</h2>
<p>Ces conditions sont régies par le droit béninois. Pour toute question :
<a href="mailto:%(contact)s">%(contact)s</a>.</p>
""" % {"contact": CONTACT}
