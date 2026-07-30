"""Contenu des pages du site Sophos Publisher."""

CONTACT = "hedjav@gmail.com"

ACCUEIL = """
<p class="chapo">Sophos Publisher est l'outil interne du ministère
<strong>Sophos PropheTikos</strong>. Il prépare et met en ligne les extraits de
prédications sur nos propres comptes, pour que l'équipe passe son temps à
enseigner plutôt qu'à manipuler des fichiers vidéo.</p>

<h2>À quoi sert cet outil</h2>
<p>Notre ministère diffuse des prédications en français, à destination du public
francophone d'Afrique de l'Ouest. Une prédication dure souvent deux à trois
heures : personne ne la regarde en entier sur un téléphone. Sophos Publisher
en tire des extraits courts et autonomes, les habille de sous-titres, puis les
publie sur nos comptes.</p>

<div class="grille">
  <div class="encart"><h3>Découper avec du sens</h3>
  <p>Chaque extrait porte une affirmation forte <em>et</em> son explication
  complète. Jamais une phrase coupée au milieu.</p></div>

  <div class="encart"><h3>Rendre lisible sans le son</h3>
  <p>Sous-titres synchronisés mot à mot, car la majorité de notre audience
  regarde sans écouter.</p></div>

  <div class="encart"><h3>Publier à heures régulières</h3>
  <p>Six mises en ligne par jour, échelonnées, sur nos propres comptes
  uniquement.</p></div>
</div>

<h2>Ce que l'outil ne fait pas</h2>
<ul>
  <li>Il ne publie <strong>que</strong> sur les comptes du ministère. Il n'agit
  jamais au nom d'un tiers.</li>
  <li>Il n'est pas proposé au public : aucune inscription, aucun compte à créer,
  aucun service vendu.</li>
  <li>Il ne collecte aucune donnée sur les personnes qui regardent nos vidéos.</li>
</ul>

<div class="encart">
<h3>Qui sommes-nous</h3>
<p>Sophos PropheTikos est un ministère chrétien basé à Cotonou, au Bénin. Nous
diffusons des enseignements, des témoignages et des temps de prière. Les
prédications proviennent de nos propres enregistrements et de ministères
partenaires qui nous en ont donné l'autorisation.</p>
<p>Contact : <a href="mailto:%s">%s</a></p>
</div>
""" % (CONTACT, CONTACT)


FONCTIONNEMENT = """
<p class="chapo">Le parcours d'une prédication, de l'enregistrement à la mise en
ligne. Aucune étape ne concerne des comptes autres que les nôtres.</p>

<h2>Les six étapes</h2>
<ol>
  <li><strong>Récupération.</strong> La prédication est récupérée depuis la
  chaîne du ministère ou d'un ministère partenaire ayant donné son accord.</li>
  <li><strong>Transcription.</strong> Les paroles sont transcrites avec
  horodatage, sur notre propre matériel. Aucun service externe n'y accède.</li>
  <li><strong>Choix des extraits.</strong> Les passages les plus forts sont
  repérés, en veillant à ce que chaque extrait garde un sens complet. Les appels
  aux dons et les annonces pratiques sont systématiquement écartés.</li>
  <li><strong>Habillage.</strong> Sous-titres, phrase d'accroche, filigrane du
  ministère. Le cadrage suit l'orateur ; quand un verset s'affiche à l'écran,
  l'image entière est conservée pour qu'il reste lisible.</li>
  <li><strong>Miniature.</strong> Une image de couverture est composée avec le
  titre et, si l'orateur est identifié avec certitude, sa photo.</li>
  <li><strong>Mise en ligne.</strong> L'extrait est déposé sur nos comptes, à
  l'un des créneaux du jour.</li>
</ol>

<h2>Notre usage des interfaces TikTok</h2>
<p>Sophos Publisher utilise deux fonctions de l'API TikTok, et rien d'autre :</p>
<table>
  <tr><th>Fonction</th><th>Pourquoi</th></tr>
  <tr><td><code>user.info.basic</code></td>
      <td>Afficher le nom du compte connecté, afin que l'équipe vérifie qu'elle
      dépose bien sur le compte du ministère et non ailleurs.</td></tr>
  <tr><td><code>video.upload</code></td>
      <td>Déposer l'extrait dans les <strong>brouillons</strong> du compte. Un
      membre de l'équipe ouvre ensuite l'application TikTok, relit et publie
      lui-même.</td></tr>
</table>
<p>Nous avons délibérément renoncé à la publication directe : nous préférons
qu'un humain valide chaque extrait avant qu'il paraisse.</p>

<div class="encart">
<h3>Qui utilise l'outil</h3>
<p>Uniquement les responsables du ministère. L'outil n'est pas distribué, n'a
pas d'inscription publique, et ne dispose d'aucun mécanisme permettant à un
tiers de connecter son propre compte.</p>
</div>
"""


CHAINE = """
<p class="chapo">Ce que nous publions, et d'où viennent les prédications.</p>

<h2>Nos comptes</h2>
<ul>
  <li><strong>YouTube</strong> —
  <a href="https://www.youtube.com/@sophos_prophetikos" rel="noopener">
  @sophos_prophetikos</a> : extraits courts et enseignements développés.</li>
  <li><strong>Facebook et Instagram</strong> — pages du ministère, où les mêmes
  extraits renvoient vers la chaîne.</li>
  <li><strong>TikTok</strong> — compte du ministère, alimenté par les brouillons
  que l'équipe relit avant publication.</li>
</ul>

<h2>Ce qu'on y trouve</h2>
<ul>
  <li>des enseignements bibliques et des exhortations ;</li>
  <li>des témoignages ;</li>
  <li>des temps de prière, de déclaration et de bénédiction.</li>
</ul>

<h2>Origine des contenus</h2>
<p>Les prédications proviennent des enregistrements du ministère et de
ministères partenaires qui nous ont autorisés à les reprendre. Chaque extrait
crédite le prédicateur et son église, et renvoie à la vidéo d'origine.</p>
<p>Un prédicateur n'est jamais nommé par supposition : son nom n'apparaît que
s'il est établi avec certitude. Dans le doute, l'extrait paraît sans
attribution.</p>

<div class="encart">
<h3>Une réclamation à formuler ?</h3>
<p>Si vous estimez qu'un extrait porte atteinte à vos droits, écrivez-nous à
<a href="mailto:%s">%s</a> en indiquant le lien concerné. Nous retirons le
contenu contesté le temps d'examiner la demande.</p>
</div>
""" % (CONTACT, CONTACT)
