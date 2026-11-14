import {
  Apple, Bacon, Banana, Bean, Beef, Candy, Carrot, Cheese, Cherry, Citrus, Coffee, Cookie, CookingPot,
  Croissant, CupSoda, Droplet, Drumstick, Egg, Fish, Flame, Flower, GlassWater, Grape, Ham, IceCreamCone,
  Layers, Leaf, LeafyGreen, Milk, Nut, Package, Pencil, Pizza, Salad, Sandwich, SoapDispenserDroplet, Soup,
  Sparkles, SprayCan, Sprout, UtensilsCrossed, Vegan, Wheat, Wine,
  type LucideIcon,
} from "lucide-react";

/**
 * A generic picture for a catalog product, read from its English or Finnish name.
 *
 * Why: Valio's product data has no image field (checked 2026-11-14: none of the 17,546
 * products, nothing in the challenge API). A real pack photo would be copied from the web,
 * so every product gets a generic picture instead: one line icon for its kind ("milk",
 * "cheese", "potato") on a soft tile tinted for the kind. It is a picture of the kind,
 * never of the product, so it can not claim a brand or a pack that is not there. A name
 * that matches no rule gets a plain package. Icons, not emoji (the UI rule forbids emoji
 * as icons); lucide has no icon for some kinds, so those take the nearest honest one.
 *
 * Rules are tried in order, so a narrower kind comes before a wider one: "ice cream"
 * before "cream", "peanut butter" before "butter", "chocolate milk" stays milk.
 * English words match at a word start; Finnish words also match as the end of a compound
 * ("kuohukerma" is cream, "juustokastike" is a sauce, not cheese).
 */

/** Soft tile colours that read in the light and the dark theme. */
export const TINTS = {
  sky: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  orange: "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300",
  rose: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  pink: "bg-pink-100 text-pink-700 dark:bg-pink-950 dark:text-pink-300",
  violet: "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300",
  green: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  stone: "bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300",
  slate: "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
} as const;
export type Tint = keyof typeof TINTS;

export interface ProductPicture {
  icon: LucideIcon;
  tint: Tint;
  /** The kind in plain English, for the picture's accessible name. */
  kind: string;
}

type Rule = [icon: LucideIcon, tint: Tint, kind: string, en: string[], fi: string[]];

// One line per kind: icon, tile colour, kind, English words, Finnish words.
const RULES: Rule[] = [
  [Layers, "slate", "napkins and table linen", ["napkin", "napkins", "tablecover", "tabelcover", "table cover", "tablecloth", "banquet", "serviette", "dunicel", "dunisoft", "doily", "tete-a-tet", "placemat", "runner", "duni"], ["lautasliina", "pöytäliina", "poikkiliina", "tabletti", "liina", "kaitaliina"]],
  [Flame, "amber", "candles", ["candle", "candles", "tealight"], ["kynttilä", "kynttilät", "lämpökynttilä"]],
  [Pencil, "slate", "office supplies", ["marker", "pen", "pencil", "stapler", "label", "tape", "battery", "batteries", "chalkboard", "envelope", "folder", "post-it", "sticky note"], ["tussi", "kynä", "nitoja", "tarra", "teippi", "paristo", "liitutaulu", "kirjekuori", "kansio"]],
  // Clear non-food words first: "napkin kiwi", "wine glass", "pizza plate", "coffee filter".
  [UtensilsCrossed, "slate", "tableware and kitchen tools", ["plate", "plates", "wine glass", "glass", "bowl", "scoop", "lid", "lids", "tray", "trays", "dispenser", "pepper mill", "coffee filter", "basket filter", "holder", "trolley", "cutlery", "skewer", "cocktail stick", "toothpick", "frypan", "food pan", "gn"], ["lautanen", "lautaset", "kulho", "kansi", "tarjotin", "annostelija", "mylly", "suodatin", "pidike", "vaunu", "aterin", "aterimet", "varras", "cocktailtikku", "hammastikku"]],
  [SprayCan, "sky", "cleaning and kitchen supplies", ["cleaner", "degreaser", "detergent", "glove", "gloves", "toilet", "garbage bag", "bin liner", "inliner", "face mask"], ["pesuaine", "puhdistusaine", "käsine", "käsineet", "wc", "jätesäkki", "roskapussi", "suojasäkki", "kasvomaski"]],
  [SoapDispenserDroplet, "sky", "personal care", ["plaster", "pad", "pads", "shampoo", "lotion", "hand cream", "toothpaste", "deodorant", "tampon", "diaper"], ["laastari", "terveysside", "shampoo", "voide", "hammastahna", "deodorantti", "tamponi", "vaippa"]],
  [IceCreamCone, "pink", "ice cream", ["ice cream", "sorbet", "gelato"], ["jäätelö", "sorbetti", "mehujää"]],
  [Nut, "stone", "nuts", ["peanut", "almond", "cashew", "hazelnut", "walnut", "pistachio", "nut mix", "nuts"], ["pähkinä", "manteli", "maapähkinä"]],
  [Cookie, "stone", "chocolate", ["chocolate", "cocoa", "praline"], ["suklaa", "kaakao"]],
  [Milk, "amber", "butter", ["butter", "margarine", "spread", "ghee"], ["voi", "margariini", "levite"]],
  [Cheese, "amber", "cheese", ["cheese", "edam", "emmental", "gouda", "cheddar", "mozzarella", "parmesan", "feta", "brie", "halloumi", "mascarpone", "ricotta", "quark", "cottage"], ["juusto", "rahka", "raejuusto", "mozzarella"]],
  [Milk, "sky", "milk and cream", ["milk", "cream", "yoghurt", "yogurt", "kefir", "buttermilk", "creme fraiche", "crème fraîche", "sour cream", "skyr", "oat drink", "milk drink", "dairy"], ["maito", "kerma", "jogurtti", "kefiiri", "piimä", "viili", "smetana", "ranskankerma", "kaurajuoma", "maitojuoma", "skyr", "kermaviili"]],
  [Egg, "amber", "eggs", ["egg", "eggs"], ["kananmuna", "muna", "munat"]],
  [Fish, "sky", "fish and seafood", ["fish", "salmon", "trout", "tuna", "cod", "herring", "flounder", "pike", "perch", "zander", "pollock", "saithe", "mackerel", "sardine", "anchovy", "shrimp", "prawn", "crab", "mussel", "seafood", "roe", "whitefish", "vendace", "surimi"], ["kala", "lohi", "taimen", "tonnikala", "turska", "silli", "silakka", "kampela", "hauki", "ahven", "kuha", "seiti", "makrilli", "katkarapu", "rapu", "simpukka", "mäti", "siika", "muikku"]],
  [Drumstick, "orange", "chicken and poultry", ["chicken", "broiler", "turkey", "duck", "poultry", "hen"], ["broileri", "kana", "kalkkuna", "ankka", "siipikarja"]],
  [Ham, "rose", "sausage", ["sausage", "frankfurter", "wiener", "hot dog", "salami", "chorizo"], ["makkara", "nakki", "salami", "lenkki"]],
  [Bacon, "rose", "ham and bacon", ["ham", "bacon", "prosciutto"], ["kinkku", "pekoni"]],
  [Beef, "rose", "meat", ["beef", "pork", "lamb", "veal", "minced", "mince", "steak", "meat", "meatball", "reindeer", "elk", "venison", "fillet", "roast", "ribs", "entrecote", "sirloin", "brisket"], ["naudan", "nauta", "sika", "possu", "lammas", "jauheliha", "liha", "lihapulla", "poro", "hirvi", "paisti", "pihvi", "filee", "kylki", "fileepihvi", "jauhis"]],
  [Vegan, "green", "plant protein", ["tofu", "tempeh", "seitan", "soy", "pulled oats", "plant-based", "vegan"], ["tofu", "soija", "nyhtökaura", "härkis", "kasvis"]],
  [Carrot, "stone", "potato", ["potato", "potatoes", "fries", "chips", "rosti", "rösti"], ["peruna", "perunat", "ranskalaiset", "sipsi", "lohkoperuna"]],
  [Carrot, "orange", "carrot and roots", ["carrot", "beetroot", "parsnip", "turnip", "swede", "celeriac", "radish", "root"], ["porkkana", "punajuuri", "palsternakka", "nauris", "lanttu", "juuriselleri", "retiisi", "juures", "juurekset"]],
  [Leaf, "green", "cucumber", ["cucumber", "gherkin", "pickle", "zucchini", "courgette"], ["kurkku", "kesäkurpitsa", "suolakurkku"]],
  [Cherry, "rose", "tomato", ["tomato", "tomatoes", "passata", "ketchup"], ["tomaatti", "tomaatit", "ketsuppi", "tomaattimurska"]],
  [Salad, "green", "salad and greens", ["lettuce", "salad", "spinach", "kale", "cabbage", "rucola", "arugula", "chard", "leek", "herb", "parsley", "dill", "basil", "coriander", "chive", "sprout", "iceberg", "romaine"], ["salaatti", "pinaatti", "lehtikaali", "kaali", "rucola", "purjo", "persilja", "tilli", "basilika", "korianteri", "ruohosipuli", "itu", "yrtti"]],
  [Coffee, "stone", "coffee and tea", ["coffee", "espresso", "tea", "cappuccino", "latte"], ["kahvi", "tee", "espresso", "suodatinkahvi"]],
  [LeafyGreen, "green", "broccoli and vegetables", ["broccoli", "cauliflower", "vegetable", "vegetables", "pea", "peas", "bean", "beans", "corn", "asparagus", "brussels", "wok mix", "edamame", "lentil", "chickpea"], ["parsakaali", "kukkakaali", "vihannes", "vihannekset", "herne", "herneet", "papu", "pavut", "maissi", "parsa", "ruusukaali", "linssi", "kikherne", "kasvissekoitus"]],
  [Sprout, "violet", "onion and garlic", ["onion", "onions", "garlic", "shallot"], ["sipuli", "valkosipuli", "salottisipuli", "punasipuli"]],
  [Flame, "rose", "pepper", ["bell pepper", "paprika", "chili", "chilli", "jalapeno", "jalapeño"], ["paprika", "chili", "jalapeno"]],
  [Leaf, "stone", "mushroom", ["mushroom", "mushrooms", "champignon", "chanterelle", "porcini"], ["sieni", "sienet", "herkkusieni", "kantarelli", "suppilovahvero", "tatti"]],
  [Apple, "rose", "apple and pear", ["apple", "pear"], ["omena", "päärynä"]],
  [Banana, "amber", "banana", ["banana"], ["banaani"]],
  [Citrus, "orange", "citrus", ["orange", "lemon", "lime", "grapefruit", "mandarin", "clementine", "citrus"], ["appelsiini", "sitruuna", "lime", "greippi", "mandariini", "klementiini"]],
  [Cherry, "violet", "berries", ["berry", "berries", "strawberry", "blueberry", "raspberry", "lingonberry", "cranberry", "currant", "bilberry", "cloudberry", "sea buckthorn"], ["marja", "marjat", "mansikka", "mustikka", "vadelma", "puolukka", "karpalo", "herukka", "lakka", "tyrni"]],
  [Grape, "violet", "fruit", ["grape", "grapes", "fruit", "melon", "pineapple", "mango", "kiwi", "peach", "plum", "cherry", "apricot", "avocado", "raisin", "date", "fig", "olive"], ["viinirypäle", "hedelmä", "hedelmät", "meloni", "ananas", "mango", "kiivi", "persikka", "luumu", "kirsikka", "aprikoosi", "avokado", "rusina", "taateli", "viikuna", "oliivi"]],
  [Pizza, "orange", "pizza", ["pizza"], ["pizza"]],
  [Croissant, "amber", "pastry", ["croissant", "pastry", "danish", "bun", "muffin", "doughnut", "donut", "pie", "cake", "cookie", "biscuit", "waffle", "pancake", "brownie", "tart", "cinnamon roll"], ["pulla", "korvapuusti", "leivos", "piirakka", "kakku", "keksi", "vohveli", "pannukakku", "letty", "munkki", "torttu", "croissant", "muffinssi", "karjalanpiirakka"]],
  [Sandwich, "amber", "bread", ["bread", "loaf", "baguette", "toast", "rye", "crispbread", "roll", "tortilla", "pita", "flatbread", "rusk", "bagel"], ["leipä", "ruisleipä", "patonki", "paahtoleipä", "näkkileipä", "sämpylä", "tortilla", "pita", "rieska", "korppu", "limppu"]],
  [Wheat, "amber", "pasta and noodles", ["pasta", "spaghetti", "macaroni", "penne", "fusilli", "lasagne", "lasagna", "tagliatelle", "noodle", "noodles", "gnocchi", "ravioli", "tortellini"], ["pasta", "spagetti", "makaroni", "nuudeli", "nuudelit", "lasagne"]],
  [Wheat, "stone", "rice and grains", ["rice", "risotto", "couscous", "quinoa", "bulgur", "barley", "porridge", "oat", "oats", "muesli", "granola", "cereal", "flakes", "semolina", "millet", "buckwheat"], ["riisi", "kuskus", "kvinoa", "bulgur", "ohra", "puuro", "kaura", "kaurahiutale", "mysli", "granola", "hiutale", "hiutaleet", "manna", "hirssi", "tattari"]],
  [Wheat, "stone", "flour and baking", ["flour", "yeast", "baking powder", "baking soda", "starch", "breadcrumbs", "dough"], ["jauho", "jauhot", "hiiva", "leivinjauhe", "tärkkelys", "korppujauho", "taikina"]],
  [Droplet, "amber", "oil and vinegar", ["oil", "vinegar", "dressing", "mayonnaise", "mayo"], ["öljy", "rypsiöljy", "oliiviöljy", "etikka", "kastike", "majoneesi", "salaatinkastike"]],
  [Soup, "orange", "sauce, soup and canned", ["sauce", "soup", "stock", "broth", "bouillon", "gravy", "pesto", "salsa", "mustard", "canned", "tinned", "concentrate", "fond", "curry", "paste"], ["kastike", "keitto", "liemi", "fondi", "pesto", "salsa", "sinappi", "säilyke", "tiiviste", "curry", "tahna"]],
  [Sparkles, "stone", "salt and spices", ["salt", "pepper", "spice", "seasoning", "cinnamon", "cardamom", "nutmeg", "oregano", "thyme", "cumin", "turmeric", "vanilla", "ginger", "clove", "bay leaf", "allspice"], ["suola", "pippuri", "mauste", "maustesekoitus", "kaneli", "kardemumma", "muskotti", "oregano", "timjami", "kumina", "kurkuma", "vanilja", "inkivääri", "neilikka", "laakerinlehti", "maustepippuri"]],
  [Candy, "pink", "sugar and sweets", ["sugar", "syrup", "honey", "jam", "marmalade", "candy", "sweets", "liquorice", "licorice", "jelly", "marshmallow", "sweetener", "dessert", "pudding"], ["sokeri", "siirappi", "hunaja", "hillo", "marmeladi", "karkki", "makeinen", "lakritsi", "hyytelö", "makeutusaine", "jälkiruoka", "vanukas", "kiisseli"]],
  [CupSoda, "orange", "juice and drinks", ["juice", "smoothie", "nectar", "lemonade", "soft drink", "cola", "drink", "beverage", "cider", "lingonberry drink"], ["mehu", "smoothie", "nektari", "limonadi", "virvoitusjuoma", "juoma", "siideri", "täysmehu"]],
  [GlassWater, "sky", "water", ["water", "mineral water", "sparkling water"], ["vesi", "kivennäisvesi"]],
  [Wine, "violet", "beer and wine", ["beer", "wine", "lager", "ale"], ["olut", "viini", "lonkero"]],
  [CookingPot, "orange", "ready meal", ["meal", "lasagne", "casserole", "wrap", "sandwich", "burger", "kebab", "nugget", "nuggets", "falafel", "spring roll", "dumpling", "sushi", "taco", "patty"], ["ateria", "valmisruoka", "makaronilaatikko", "perunalaatikko", "lihalaatikko", "kääre", "voileipä", "hampurilainen", "kebab", "pyörykkä", "pihvi", "sushi", "taco"]],
  [Bean, "green", "seeds", ["seed", "seeds", "linseed", "sesame", "chia"], ["siemen", "siemenet", "pellavansiemen", "seesami", "chia"]],
  [UtensilsCrossed, "slate", "tableware and kitchen tools", ["bowl", "knife", "knives", "fork", "spoon", "pan", "frypan", "pot", "tong", "tongs", "whisk", "tumbler", "glass", "glasses", "mug", "jug", "pitcher", "ladle", "spatula", "grater", "peeler", "cutting board", "board", "sieve", "scale", "thermometer", "gastronorm", "rack", "grill", "trolley", "bin", "dispenser", "holder", "stand", "saucer", "dish", "carafe"], ["kulho", "astia", "veitsi", "haarukka", "lusikka", "pannu", "paistinpannu", "kattila", "otin", "otti", "vispilä", "lasi", "lasit", "kannu", "kauha", "lasta", "raastin", "kuorimaveitsi", "leikkuulauta", "siivilä", "vaaka", "lämpömittari", "ritilä", "grilli", "vaunu", "teline", "pidike", "annostelija", "tarjotin", "karahvi", "lautanen"]],
  [Flower, "pink", "flowers", ["flower", "flowers", "plant", "bouquet"], ["kukka", "kukat", "kimppu", "ruukkukasvi"]],
  [SprayCan, "sky", "cleaning and kitchen supplies", ["detergent", "cleaner", "cleaning", "soap", "dishwasher", "napkin", "glove", "gloves", "foil", "film", "bag", "bags", "paper", "towel", "cup", "cups", "plate", "lid", "straw", "container", "tray", "rinse aid"], ["pesuaine", "puhdistus", "saippua", "astianpesu", "lautasliina", "käsine", "käsineet", "folio", "kelmu", "pussi", "paperi", "pyyhe", "muki", "lautanen", "kansi", "pilli", "rasia", "vuoka", "huuhtelu"]],
];

const FALLBACK: ProductPicture = { icon: Package, tint: "slate", kind: "product" };

const escape = (word: string) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// An English word starts at a word boundary; a plural "s" is fine. A Finnish word may end a compound.
const COMPILED = RULES.map(([icon, tint, kind, en, fi]) => ({
  picture: { icon, tint, kind } satisfies ProductPicture,
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
