/**
 * A generic picture for a catalog product, read from its English or Finnish name.
 *
 * Why: Valio's product data has no image field (checked 2026-11-14: none of the 17,546
 * products, nothing in the challenge API). A real pack photo would be copied from the web,
 * so every product gets a generic food picture instead: one emoji for its kind ("milk",
 * "cheese", "potato"). It is a picture of the kind, never of the product, so it can not
 * claim a brand or a pack that is not there. A name that matches no rule gets a plain
 * parcel.
 *
 * Rules are tried in order, so a narrower kind comes before a wider one: "ice cream"
 * before "cream", "peanut butter" before "butter", "chocolate milk" stays milk.
 * English words match at a word start; Finnish words also match as the end of a compound
 * ("kuohukerma" is cream, "juustokastike" is a sauce, not cheese).
 */
export interface ProductPicture {
  emoji: string;
  /** The kind in plain English, for the picture's accessible name. */
  kind: string;
}

type Rule = [emoji: string, kind: string, en: string[], fi: string[]];

// The tile colour follows the emoji, so the list stays one line per kind.
const RULES: Rule[] = [
  ["🧻", "napkins and table linen", ["napkin", "napkins", "tablecover", "tabelcover", "table cover", "tablecloth", "banquet", "serviette", "dunicel", "dunisoft", "doily", "tete-a-tet", "placemat", "runner", "duni"], ["lautasliina", "pöytäliina", "poikkiliina", "tabletti", "liina", "kaitaliina"]],
  ["🕯️", "candles", ["candle", "candles", "tealight"], ["kynttilä", "kynttilät", "lämpökynttilä"]],
  ["✏️", "office supplies", ["marker", "pen", "pencil", "stapler", "label", "tape", "battery", "batteries", "chalkboard", "envelope", "folder", "post-it", "sticky note"], ["tussi", "kynä", "nitoja", "tarra", "teippi", "paristo", "liitutaulu", "kirjekuori", "kansio"]],
  // Clear non-food words first: "napkin kiwi", "wine glass", "pizza plate", "coffee filter".
  ["🍴", "tableware and kitchen tools", ["plate", "plates", "wine glass", "glass", "bowl", "scoop", "lid", "lids", "tray", "trays", "dispenser", "pepper mill", "coffee filter", "basket filter", "holder", "trolley", "cutlery", "skewer", "cocktail stick", "toothpick", "frypan", "food pan", "gn"], ["lautanen", "lautaset", "kulho", "kansi", "tarjotin", "annostelija", "mylly", "suodatin", "pidike", "vaunu", "aterin", "aterimet", "varras", "cocktailtikku", "hammastikku"]],
  ["🧽", "cleaning and kitchen supplies", ["cleaner", "degreaser", "detergent", "glove", "gloves", "toilet", "garbage bag", "bin liner", "inliner", "face mask"], ["pesuaine", "puhdistusaine", "käsine", "käsineet", "wc", "jätesäkki", "roskapussi", "suojasäkki", "kasvomaski"]],
  ["🧴", "personal care", ["plaster", "pad", "pads", "shampoo", "lotion", "hand cream", "toothpaste", "deodorant", "tampon", "diaper"], ["laastari", "terveysside", "shampoo", "voide", "hammastahna", "deodorantti", "tamponi", "vaippa"]],
  ["🍨", "ice cream", ["ice cream", "sorbet", "gelato"], ["jäätelö", "sorbetti", "mehujää"]],
  ["🥜", "nuts", ["peanut", "almond", "cashew", "hazelnut", "walnut", "pistachio", "nut mix", "nuts"], ["pähkinä", "manteli", "maapähkinä"]],
  ["🍫", "chocolate", ["chocolate", "cocoa", "praline"], ["suklaa", "kaakao"]],
  ["🧈", "butter", ["butter", "margarine", "spread", "ghee"], ["voi", "margariini", "levite"]],
  ["🧀", "cheese", ["cheese", "edam", "emmental", "gouda", "cheddar", "mozzarella", "parmesan", "feta", "brie", "halloumi", "mascarpone", "ricotta", "quark", "cottage"], ["juusto", "rahka", "raejuusto", "mozzarella"]],
  ["🥛", "milk and cream", ["milk", "cream", "yoghurt", "yogurt", "kefir", "buttermilk", "creme fraiche", "crème fraîche", "sour cream", "skyr", "oat drink", "milk drink", "dairy"], ["maito", "kerma", "jogurtti", "kefiiri", "piimä", "viili", "smetana", "ranskankerma", "kaurajuoma", "maitojuoma", "skyr", "kermaviili"]],
  ["🥚", "eggs", ["egg", "eggs"], ["kananmuna", "muna", "munat"]],
  ["🐟", "fish and seafood", ["fish", "salmon", "trout", "tuna", "cod", "herring", "flounder", "pike", "perch", "zander", "pollock", "saithe", "mackerel", "sardine", "anchovy", "shrimp", "prawn", "crab", "mussel", "seafood", "roe", "whitefish", "vendace", "surimi"], ["kala", "lohi", "taimen", "tonnikala", "turska", "silli", "silakka", "kampela", "hauki", "ahven", "kuha", "seiti", "makrilli", "katkarapu", "rapu", "simpukka", "mäti", "siika", "muikku"]],
  ["🍗", "chicken and poultry", ["chicken", "broiler", "turkey", "duck", "poultry", "hen"], ["broileri", "kana", "kalkkuna", "ankka", "siipikarja"]],
  ["🌭", "sausage", ["sausage", "frankfurter", "wiener", "hot dog", "salami", "chorizo"], ["makkara", "nakki", "salami", "lenkki"]],
  ["🥓", "ham and bacon", ["ham", "bacon", "prosciutto"], ["kinkku", "pekoni"]],
  ["🥩", "meat", ["beef", "pork", "lamb", "veal", "minced", "mince", "steak", "meat", "meatball", "reindeer", "elk", "venison", "fillet", "roast", "ribs", "entrecote", "sirloin", "brisket"], ["naudan", "nauta", "sika", "possu", "lammas", "jauheliha", "liha", "lihapulla", "poro", "hirvi", "paisti", "pihvi", "filee", "kylki", "fileepihvi", "jauhis"]],
  ["🌱", "plant protein", ["tofu", "tempeh", "seitan", "soy", "pulled oats", "plant-based", "vegan"], ["tofu", "soija", "nyhtökaura", "härkis", "kasvis"]],
  ["🥔", "potato", ["potato", "potatoes", "fries", "chips", "rosti", "rösti"], ["peruna", "perunat", "ranskalaiset", "sipsi", "lohkoperuna"]],
  ["🥕", "carrot and roots", ["carrot", "beetroot", "parsnip", "turnip", "swede", "celeriac", "radish", "root"], ["porkkana", "punajuuri", "palsternakka", "nauris", "lanttu", "juuriselleri", "retiisi", "juures", "juurekset"]],
  ["🥒", "cucumber", ["cucumber", "gherkin", "pickle", "zucchini", "courgette"], ["kurkku", "kesäkurpitsa", "suolakurkku"]],
  ["🍅", "tomato", ["tomato", "tomatoes", "passata", "ketchup"], ["tomaatti", "tomaatit", "ketsuppi", "tomaattimurska"]],
  ["🥬", "salad and greens", ["lettuce", "salad", "spinach", "kale", "cabbage", "rucola", "arugula", "chard", "leek", "herb", "parsley", "dill", "basil", "coriander", "chive", "sprout", "iceberg", "romaine"], ["salaatti", "pinaatti", "lehtikaali", "kaali", "rucola", "purjo", "persilja", "tilli", "basilika", "korianteri", "ruohosipuli", "itu", "yrtti"]],
  ["☕", "coffee and tea", ["coffee", "espresso", "tea", "cappuccino", "latte"], ["kahvi", "tee", "espresso", "suodatinkahvi"]],
  ["🥦", "broccoli and vegetables", ["broccoli", "cauliflower", "vegetable", "vegetables", "pea", "peas", "bean", "beans", "corn", "asparagus", "brussels", "wok mix", "edamame", "lentil", "chickpea"], ["parsakaali", "kukkakaali", "vihannes", "vihannekset", "herne", "herneet", "papu", "pavut", "maissi", "parsa", "ruusukaali", "linssi", "kikherne", "kasvissekoitus"]],
  ["🧅", "onion and garlic", ["onion", "onions", "garlic", "shallot"], ["sipuli", "valkosipuli", "salottisipuli", "punasipuli"]],
  ["🫑", "pepper", ["bell pepper", "paprika", "chili", "chilli", "jalapeno", "jalapeño"], ["paprika", "chili", "jalapeno"]],
  ["🍄", "mushroom", ["mushroom", "mushrooms", "champignon", "chanterelle", "porcini"], ["sieni", "sienet", "herkkusieni", "kantarelli", "suppilovahvero", "tatti"]],
  ["🍎", "apple and pear", ["apple", "pear"], ["omena", "päärynä"]],
  ["🍌", "banana", ["banana"], ["banaani"]],
  ["🍊", "citrus", ["orange", "lemon", "lime", "grapefruit", "mandarin", "clementine", "citrus"], ["appelsiini", "sitruuna", "lime", "greippi", "mandariini", "klementiini"]],
  ["🍓", "berries", ["berry", "berries", "strawberry", "blueberry", "raspberry", "lingonberry", "cranberry", "currant", "bilberry", "cloudberry", "sea buckthorn"], ["marja", "marjat", "mansikka", "mustikka", "vadelma", "puolukka", "karpalo", "herukka", "lakka", "tyrni"]],
  ["🍇", "fruit", ["grape", "grapes", "fruit", "melon", "pineapple", "mango", "kiwi", "peach", "plum", "cherry", "apricot", "avocado", "raisin", "date", "fig", "olive"], ["viinirypäle", "hedelmä", "hedelmät", "meloni", "ananas", "mango", "kiivi", "persikka", "luumu", "kirsikka", "aprikoosi", "avokado", "rusina", "taateli", "viikuna", "oliivi"]],
  ["🍕", "pizza", ["pizza"], ["pizza"]],
  ["🥐", "pastry", ["croissant", "pastry", "danish", "bun", "muffin", "doughnut", "donut", "pie", "cake", "cookie", "biscuit", "waffle", "pancake", "brownie", "tart", "cinnamon roll"], ["pulla", "korvapuusti", "leivos", "piirakka", "kakku", "keksi", "vohveli", "pannukakku", "letty", "munkki", "torttu", "croissant", "muffinssi", "karjalanpiirakka"]],
  ["🍞", "bread", ["bread", "loaf", "baguette", "toast", "rye", "crispbread", "roll", "tortilla", "pita", "flatbread", "rusk", "bagel"], ["leipä", "ruisleipä", "patonki", "paahtoleipä", "näkkileipä", "sämpylä", "tortilla", "pita", "rieska", "korppu", "limppu"]],
  ["🍝", "pasta and noodles", ["pasta", "spaghetti", "macaroni", "penne", "fusilli", "lasagne", "lasagna", "tagliatelle", "noodle", "noodles", "gnocchi", "ravioli", "tortellini"], ["pasta", "spagetti", "makaroni", "nuudeli", "nuudelit", "lasagne"]],
  ["🍚", "rice and grains", ["rice", "risotto", "couscous", "quinoa", "bulgur", "barley", "porridge", "oat", "oats", "muesli", "granola", "cereal", "flakes", "semolina", "millet", "buckwheat"], ["riisi", "kuskus", "kvinoa", "bulgur", "ohra", "puuro", "kaura", "kaurahiutale", "mysli", "granola", "hiutale", "hiutaleet", "manna", "hirssi", "tattari"]],
  ["🌾", "flour and baking", ["flour", "yeast", "baking powder", "baking soda", "starch", "breadcrumbs", "dough"], ["jauho", "jauhot", "hiiva", "leivinjauhe", "tärkkelys", "korppujauho", "taikina"]],
  ["🫒", "oil and vinegar", ["oil", "vinegar", "dressing", "mayonnaise", "mayo"], ["öljy", "rypsiöljy", "oliiviöljy", "etikka", "kastike", "majoneesi", "salaatinkastike"]],
  ["🥫", "sauce, soup and canned", ["sauce", "soup", "stock", "broth", "bouillon", "gravy", "pesto", "salsa", "mustard", "canned", "tinned", "concentrate", "fond", "curry", "paste"], ["kastike", "keitto", "liemi", "fondi", "pesto", "salsa", "sinappi", "säilyke", "tiiviste", "curry", "tahna"]],
  ["🧂", "salt and spices", ["salt", "pepper", "spice", "seasoning", "cinnamon", "cardamom", "nutmeg", "oregano", "thyme", "cumin", "turmeric", "vanilla", "ginger", "clove", "bay leaf", "allspice"], ["suola", "pippuri", "mauste", "maustesekoitus", "kaneli", "kardemumma", "muskotti", "oregano", "timjami", "kumina", "kurkuma", "vanilja", "inkivääri", "neilikka", "laakerinlehti", "maustepippuri"]],
  ["🍬", "sugar and sweets", ["sugar", "syrup", "honey", "jam", "marmalade", "candy", "sweets", "liquorice", "licorice", "jelly", "marshmallow", "sweetener", "dessert", "pudding"], ["sokeri", "siirappi", "hunaja", "hillo", "marmeladi", "karkki", "makeinen", "lakritsi", "hyytelö", "makeutusaine", "jälkiruoka", "vanukas", "kiisseli"]],
  ["🧃", "juice and drinks", ["juice", "smoothie", "nectar", "lemonade", "soft drink", "cola", "drink", "beverage", "cider", "lingonberry drink"], ["mehu", "smoothie", "nektari", "limonadi", "virvoitusjuoma", "juoma", "siideri", "täysmehu"]],
  ["💧", "water", ["water", "mineral water", "sparkling water"], ["vesi", "kivennäisvesi"]],
  ["🍺", "beer and wine", ["beer", "wine", "lager", "ale"], ["olut", "viini", "lonkero"]],
  ["🍽️", "ready meal", ["meal", "lasagne", "casserole", "wrap", "sandwich", "burger", "kebab", "nugget", "nuggets", "falafel", "spring roll", "dumpling", "sushi", "taco", "patty"], ["ateria", "valmisruoka", "makaronilaatikko", "perunalaatikko", "lihalaatikko", "kääre", "voileipä", "hampurilainen", "kebab", "pyörykkä", "pihvi", "sushi", "taco"]],
  ["🌻", "seeds", ["seed", "seeds", "linseed", "sesame", "chia"], ["siemen", "siemenet", "pellavansiemen", "seesami", "chia"]],
  ["🍴", "tableware and kitchen tools", ["bowl", "knife", "knives", "fork", "spoon", "pan", "frypan", "pot", "tong", "tongs", "whisk", "tumbler", "glass", "glasses", "mug", "jug", "pitcher", "ladle", "spatula", "grater", "peeler", "cutting board", "board", "sieve", "scale", "thermometer", "gastronorm", "rack", "grill", "trolley", "bin", "dispenser", "holder", "stand", "saucer", "dish", "carafe"], ["kulho", "astia", "veitsi", "haarukka", "lusikka", "pannu", "paistinpannu", "kattila", "otin", "otti", "vispilä", "lasi", "lasit", "kannu", "kauha", "lasta", "raastin", "kuorimaveitsi", "leikkuulauta", "siivilä", "vaaka", "lämpömittari", "ritilä", "grilli", "vaunu", "teline", "pidike", "annostelija", "tarjotin", "karahvi", "lautanen"]],
  ["💐", "flowers", ["flower", "flowers", "plant", "bouquet"], ["kukka", "kukat", "kimppu", "ruukkukasvi"]],
  ["🧽", "cleaning and kitchen supplies", ["detergent", "cleaner", "cleaning", "soap", "dishwasher", "napkin", "glove", "gloves", "foil", "film", "bag", "bags", "paper", "towel", "cup", "cups", "plate", "lid", "straw", "container", "tray", "rinse aid"], ["pesuaine", "puhdistus", "saippua", "astianpesu", "lautasliina", "käsine", "käsineet", "folio", "kelmu", "pussi", "paperi", "pyyhe", "muki", "lautanen", "kansi", "pilli", "rasia", "vuoka", "huuhtelu"]],
];

const FALLBACK: ProductPicture = { emoji: "📦", kind: "product" };

const escape = (word: string) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// An English word starts at a word boundary; a plural "s" is fine. A Finnish word may end a compound.
const COMPILED = RULES.map(([emoji, kind, en, fi]) => ({
  picture: { emoji, kind },
  en: new RegExp(`(?:^|[^\\p{L}])(?:${en.map(escape).join("|")})(?:s|es)?(?![\\p{L}])`, "iu"),
  fi: new RegExp(`(?:${fi.map(escape).join("|")})(?:t|a|ä)?(?![\\p{L}])`, "iu"),
}));

/** The generic picture for a product, from its English and Finnish names. */
export function pictureFor(en?: string | null, fi?: string | null): ProductPicture {
  const english = (en ?? "").trim();
  const finnish = (fi ?? "").trim();
  for (const rule of COMPILED) {
    if ((english && rule.en.test(english)) || (finnish && rule.fi.test(finnish))) return rule.picture;
  }
  return FALLBACK;
}

export const FALLBACK_PICTURE = FALLBACK;
