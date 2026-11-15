// "What Nemotron did" panel (#1197): components/purchasing/model-trace-panel.tsx.
export default {
  "What Nemotron did": "Mitä Nemotron teki",
  // The visible line on the card and the explanation call in the panel (#1867).
  "Picked by {model} · 1 call · {seconds} s": "Valinnut {model} · 1 kutsu · {seconds} s",
  "Picked by {model} · {calls} calls · {seconds} s": "Valinnut {model} · {calls} kutsua · {seconds} s",
  "Picked by a model": "Mallin valitsema",
  "Made by the gateway’s rules, no model call": "Yhdyskäytävän sääntöjen tekemä, ei mallikutsua",
  " · 1 call · {seconds} s": " · 1 kutsu · {seconds} s",
  "Wrote the explanation on this card from the checked decision record":
    "Kirjoitti tämän kortin selityksen tarkistetun päätöstietueen pohjalta",
  "Wrote the explanation on this card from the checked decision record: {seconds} s":
    "Kirjoitti tämän kortin selityksen tarkistetun päätöstietueen pohjalta: {seconds} s",
  "The gateway’s request parser made the proposal: no model picked the products.":
    "Yhdyskäytävän pyyntöjen jäsennin teki ehdotuksen: mikään malli ei valinnut tuotteita.",
  "Picked by rule: no model picked the products.": "Valittu säännöllä: mikään malli ei valinnut tuotteita.",
  "{model} wrote the explanation on this card: 1 model call.": "{model} kirjoitti tämän kortin selityksen: 1 mallikutsu.",
  "{model} wrote the explanation on this card: 1 model call, {seconds} s.":
    "{model} kirjoitti tämän kortin selityksen: 1 mallikutsu, {seconds} s.",
  "1 model call, {seconds} s, thinking on": "1 mallikutsu, {seconds} s, ajattelu päällä",
  "{calls} model calls, {seconds} s, thinking on": "{calls} mallikutsua, {seconds} s, ajattelu päällä",
  "1 model call, {seconds} s, thinking off": "1 mallikutsu, {seconds} s, ajattelu pois",
  "{calls} model calls, {seconds} s, thinking off": "{calls} mallikutsua, {seconds} s, ajattelu pois",
  "0 model calls (pick reused)": "0 mallikutsua (valinta käytetty uudelleen)",
  "1 model call, {seconds} s": "1 mallikutsu, {seconds} s",
  "{calls} model calls, {seconds} s": "{calls} mallikutsua, {seconds} s",
  "Quantities and prices: the engine. Approval: you.": "Määrät ja hinnat: moottori. Hyväksyntä: sinä.",
  "The gateway’s request parser answered. No model ran.": "Yhdyskäytävän pyyntöjen jäsennin vastasi. Mallia ei käytetty.",
  "Picked by rule. No model ran.": "Valittu säännöllä. Mallia ei käytetty.",
  "The first run stopped without a proposal and was started once more.":
    "Ensimmäinen ajo pysähtyi ilman ehdotusta, ja se aloitettiin kerran uudelleen.",
  "No tool steps were recorded.": "Työkaluvaiheita ei tallennettu.",
  "Later steps were cut.": "Myöhemmät vaiheet jätettiin pois.",
  "Model:": "Malli:",
  "Code:": "Koodi:",
  "needs a person’s approval": "vaatii ihmisen hyväksynnän",
  "refused": "hylätty",
  "Searched the catalog": "Haki tuoteluettelosta",
  "Searched the catalog for “{query}”: {count} products": "Haki tuoteluettelosta ”{query}”: {count} tuotetta",
  "Searched the catalog: {count} products": "Haki tuoteluettelosta: {count} tuotetta",
  "Asked the engine for an offer": "Pyysi moottorilta tarjouksen",
  "Asked the engine for an offer on {products} products: {count} lines":
    "Pyysi moottorilta tarjouksen {products} tuotteelle: {count} riviä",
  "Checked the offer against the guards": "Tarkisti tarjouksen suojasääntöjä vasten",
  "Checked the offer against the guards: {verdict}": "Tarkisti tarjouksen suojasääntöjä vasten: {verdict}",
  "Sent the offer to you for approval": "Lähetti tarjouksen sinulle hyväksyttäväksi",
  "Placed the approved order": "Teki hyväksytyn tilauksen",
  "Read the order status": "Luki tilauksen tilan",
  "Read the activity log": "Luki toimintalokin",
  "Built a shortlist of {count} products from the catalog": "Kokosi tuoteluettelosta {count} tuotteen lyhytlistan",
  "Picked one product from the shortlist": "Valitsi lyhytlistalta yhden tuotteen",
  "The rule picked the first product": "Sääntö valitsi ensimmäisen tuotteen",
  "Reused Nemotron’s pick for the same request from a few minutes ago":
    "Käytti uudelleen Nemotronin valintaa samaan pyyntöön muutaman minuutin takaa",
  "Made a call the policy could not read": "Teki kutsun, jota sääntö ei pystynyt lukemaan",
  "{action} — refused by the policy ({code})": "{action} – sääntö hylkäsi ({code})",
  "{action} — the tool failed": "{action} – työkalu epäonnistui",
  "{action} — found by meaning (Atlas Vector Search) after the word search found nothing":
    "{action} – löytyi merkityksen perusteella (Atlas Vector Search), kun sanahaku ei löytänyt mitään",
};
