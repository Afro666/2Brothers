import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import type { Draft } from "@/api/types";
import { AppShell } from "@/components/purchasing/app-shell";
import { AllergenList, AllergenUnknownChip } from "@/components/purchasing/chips";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatEur, formatNumber } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import type {
  Allergen,
  AllergenPresence,
  OwnProduct,
  Product,
  ProductCode,
  Recipe,
  RecipeItem,
  Supplier,
} from "@/types";
import { ProductPicker, type PickerProduct } from "@/pages/products/product-picker";
import { recipeAllergens } from "@/pages/products/recipe-allergens";
import { catalogProductIdsInRecipes } from "@/pages/products/recipe-products";

/** How long whenSteady waits for a previous dialog to leave the DOM before it runs anyway. */
const STEADY_LIMIT_MS = 400;
const STEADY_RETRY_MS = 16;

const ALLERGENS = [
  ["AM", "Milk"],
  ["AW", "Gluten cereals"],
  ["AE", "Egg"],
  ["AF", "Fish"],
  ["AN", "Tree nuts"],
  ["AP", "Peanuts"],
  ["AS", "Sesame"],
  ["AY", "Soy"],
] as const;

function productName(product: Product | OwnProduct): string {
  return "names" in product ? product.names.en : product.name;
}

/** A recipe row in the editor: the quantity as typed, and a key that survives removing a row above it. */
type RecipeRow = Omit<RecipeItem, "qtyPerPortion"> & { qtyPerPortion: string; key: string };

let rowKeys = 0;
function newRowKey(): string {
  rowKeys += 1;
  return `recipe-row-${rowKeys}`;
}

async function loadData(api: ReturnType<typeof useApi>) {
  const [ownProducts, suppliers, recipes] = await Promise.all([
    api.listOwnProducts(),
    api.listSuppliers(),
    api.listRecipes(),
  ]);
  // The catalog search returns only a page, so recipes load their products by id instead.
  // A failing catalog lookup must not hide own products and suppliers: recipes then show unknown allergens.
  const catalog = await api
    .getProducts(catalogProductIdsInRecipes(recipes, ownProducts))
    .catch((): Awaited<ReturnType<typeof api.getProducts>> => []);
  return { ownProducts, suppliers, recipes, catalog };
}

/** The name, unit and origin a recipe row shows for one product. */
function pickerProduct(product: Product | OwnProduct, suppliers: readonly Supplier[]): PickerProduct {
  if ("names" in product) {
    return {
      product,
      name: product.names.en,
      unit: product.baseUnit,
      source: product.vendorName || "Supplier not set",
    };
  }
  const supplier = suppliers.find((candidate) => candidate.id === product.supplierId);
  return { product, name: product.name, unit: product.unit, source: supplier?.name ?? "Supplier not found" };
}

function ProductsTable({
  products,
  suppliers,
  onEdit,
  onDelete,
}: {
  products: OwnProduct[];
  suppliers: Supplier[];
  onEdit: (product: OwnProduct) => void;
  onDelete: (product: OwnProduct) => void;
}) {
  const supplierNames = new Map(suppliers.map((supplier) => [supplier.id, supplier.name]));
  return (
    <div className="space-y-3">
      {products.map((product) => (
        <Card key={product.id}>
          <CardContent className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-center">
            <div>
              <p className="font-medium">{product.name}</p>
              <p className="text-sm text-muted-foreground">
                {product.unit}
                {product.packSize == null ? "" : ` · pack ${formatNumber(product.packSize)}`} ·{" "}
                {product.priceEur == null ? "not set" : formatEur(product.priceEur)}
              </p>
            </div>
            <div className="space-y-1 text-sm">
              <p>{supplierNames.get(product.supplierId) ?? "Supplier not found"}</p>
              <AllergenList allergens={product.allergens} />
            </div>
            <div className="flex gap-2">
              <Button variant="outline" aria-label={`Edit ${product.name}`} onClick={() => onEdit(product)}>
                Edit
              </Button>
              <Button variant="destructive" aria-label={`Delete ${product.name}`} onClick={() => onDelete(product)}>
                Delete
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ProductsPageContent() {
  const api = useApi();
  const [tab, setTab] = useState("products");
  const state = useAsync(() => loadData(api), [api]);
  const [dialog, setDialog] = useState<"product" | "recipe" | "delete-product" | "delete-recipe" | null>(null);
  const [editingProduct, setEditingProduct] = useState<OwnProduct | null>(null);
  const [editingRecipe, setEditingRecipe] = useState<Recipe | null>(null);
  const [deletingProduct, setDeletingProduct] = useState<OwnProduct | null>(null);
  const [deletingRecipe, setDeletingRecipe] = useState<Recipe | null>(null);
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("");
  const [packSize, setPackSize] = useState("");
  const [price, setPrice] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [unknown, setUnknown] = useState(true);
  const [allergenValues, setAllergenValues] = useState<Record<string, AllergenPresence>>({});
  const [items, setItems] = useState<RecipeRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const products = state.status === "ready" ? state.data.ownProducts : [];
  const suppliers = state.status === "ready" ? state.data.suppliers : [];
  const recipes = state.status === "ready" ? state.data.recipes : [];
  const catalog = state.status === "ready" ? state.data.catalog : [];
  const productLookup = useMemo(
    () =>
      new Map<string, Product | OwnProduct>([
        ...products.map((product) => [product.id, product] as const),
        ...catalog.map((product) => [product.id, product] as const),
      ]),
    [products, catalog],
  );
  const searchProducts = useCallback(async (query: string) => api.searchProducts(query), [api]);
  const loadProducts = useCallback(async (ids: ProductCode[]) => api.getProducts(ids), [api]);
  const findPickerProduct = useCallback(
    (id: string) => {
      const product = productLookup.get(id);
      return product ? pickerProduct(product, suppliers) : undefined;
    },
    [productLookup, suppliers],
  );

  /** Opens or closes a dialog once the browser has removed its previous one; a remount would drop a half-typed form. */
  /** Gives up waiting after STEADY_LIMIT_MS and runs the callback anyway, so a stray dialog cannot block a click. */
  function whenSteady(callback: () => void) {
    const expected = dialog === null ? 0 : 1;
    const deadline = Date.now() + STEADY_LIMIT_MS;
    const attempt = () => {
      if (document.querySelectorAll("[role='dialog']").length === expected || Date.now() >= deadline) callback();
      else window.setTimeout(attempt, STEADY_RETRY_MS);
    };
    window.queueMicrotask(attempt);
  }
  function openProduct(product: OwnProduct | null = null) {
    setEditingProduct(product);
    setName(product?.name ?? "");
    setUnit(product?.unit ?? "");
    setPackSize(product?.packSize == null ? "" : String(product.packSize));
    setPrice(product?.priceEur == null ? "" : String(product.priceEur));
    setSupplierId(product?.supplierId ?? suppliers[0]?.id ?? "");
    setUnknown(product ? product.allergens === null : true);
    setAllergenValues(
      Object.fromEntries((product?.allergens ?? []).map((allergen) => [allergen.code, allergen.presence])),
    );
    setError("");
    whenSteady(() => setDialog("product"));
  }
  function openRecipe(recipe: Recipe | null = null) {
    // The header can take the click that closes a dialog, so an opened recipe editor also shows its tab.
    setTab("recipes");
    setEditingRecipe(recipe);
    setName(recipe?.name ?? "");
    setItems(
      recipe
        ? recipe.items.map((item) => ({ ...item, qtyPerPortion: String(item.qtyPerPortion), key: newRowKey() }))
        : [],
    );
    setError("");
    whenSteady(() => setDialog("recipe"));
  }
  function chooseProduct(index: number, choice: PickerProduct) {
    setItems((rows) =>
      rows.map((row, rowIndex) =>
        rowIndex === index
          ? { ...row, productId: choice.product.id, productName: choice.name, unit: choice.unit }
          : row,
      ),
    );
  }
  function clearProduct(index: number) {
    setItems((rows) =>
      rows.map((row, rowIndex) => (rowIndex === index ? { ...row, productId: "", productName: "", unit: "" } : row)),
    );
  }
  async function saveProduct(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const allergens: Allergen[] = unknown
      ? []
      : [
          ...(editingProduct?.allergens ?? []).filter(
            (allergen) => !ALLERGENS.some(([code]) => code === allergen.code),
          ),
          ...ALLERGENS.flatMap(([code, allergenName]) =>
            allergenValues[code] ? [{ code, name: allergenName, presence: allergenValues[code] }] : [],
          ),
        ];
    try {
      await api.saveOwnProduct({
        ...(editingProduct ? { id: editingProduct.id } : {}),
        name,
        unit,
        packSize: packSize === "" ? null : Number(packSize),
        priceEur: price === "" ? null : Number(price),
        supplierId,
        allergens: unknown ? null : allergens,
      } as Draft<OwnProduct>);
      resetProductForm();
      toast.success("Product saved");
      whenSteady(() => setDialog(null));
      state.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }
  // A hidden form must not submit by itself, or its stale values would overwrite the saved one.
  function resetProductForm() {
    setName("");
    setUnit("");
    setPackSize("");
    setPrice("");
    setUnknown(true);
    setAllergenValues({});
    setSupplierId(suppliers[0]?.id ?? "");
  }
  async function saveRecipe(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (items.some((item) => item.productId === "")) {
      setError("Choose a product for each item.");
      return;
    }
    if (items.length === 0) {
      setError("Add at least one item to the recipe.");
      return;
    }
    // A Finnish keypad types a decimal comma.
    const quantities = items.map((item) => Number(item.qtyPerPortion.replace(",", ".")));
    if (quantities.some((quantity) => !Number.isFinite(quantity) || quantity <= 0)) {
      setError("Each quantity per portion must be greater than 0.");
      return;
    }
    setBusy(true);
    setError("");
    const resolved = items.map(({ key: _key, ...item }, index) => {
      const product = productLookup.get(item.productId);
      return {
        ...item,
        qtyPerPortion: quantities[index],
        productName: product ? productName(product) : item.productName,
        unit: product ? ("baseUnit" in product ? product.baseUnit : product.unit) : item.unit,
      };
    });
    try {
      await api.saveRecipe({
        ...(editingRecipe ? { id: editingRecipe.id } : {}),
        name,
        items: resolved,
      } as Draft<Recipe>);
      setItems([]);
      toast.success("Recipe saved");
      whenSteady(() => setDialog(null));
      state.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }
  async function removeProduct() {
    if (!deletingProduct) return;
    setBusy(true);
    setError("");
    try {
      await api.deleteOwnProduct(deletingProduct.id);
      toast.success("Product deleted");
      whenSteady(() => setDialog(null));
      state.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }
  async function removeRecipe() {
    if (!deletingRecipe) return;
    setBusy(true);
    setError("");
    try {
      await api.deleteRecipe(deletingRecipe.id);
      toast.success("Recipe deleted");
      whenSteady(() => setDialog(null));
      state.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  const labelClass = "grid gap-1.5 text-sm font-medium";
  const actionError = error ? (
    <p role="alert" className="text-sm text-destructive">
      {error}
    </p>
  ) : null;
  return (
    <AppShell activeId="products">
      <div className="mx-auto max-w-5xl space-y-6">
        <header>
          <h1 className="text-2xl font-semibold">Recipes</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Your recipes and the products you make in-house, with their purchasing data.
          </p>
        </header>
        {state.status === "loading" ? <LoadingState label="Loading products and recipes" /> : null}
        {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
        {state.status === "ready" ? (
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="products">Products</TabsTrigger>
              <TabsTrigger value="recipes">Recipes</TabsTrigger>
            </TabsList>
            <TabsContent value="products" className="space-y-4">
              <div className="flex justify-end">
                <Button onClick={() => openProduct()}>Add product</Button>
              </div>
              {products.length ? (
                <ProductsTable
                  products={products}
                  suppliers={suppliers}
                  onEdit={openProduct}
                  onDelete={(product) => {
                    setDeletingProduct(product);
                    setError("");
                    setDialog("delete-product");
                  }}
                />
              ) : (
                <EmptyState title="No own products yet">Add products the kitchen buys outside the catalog.</EmptyState>
              )}
            </TabsContent>
            <TabsContent value="recipes" className="space-y-4">
              <div className="flex justify-end">
                <Button onClick={() => openRecipe()}>Add recipe</Button>
              </div>
              {recipes.length ? (
                <div className="space-y-3">
                  {recipes.map((recipe) => {
                    const summary = recipeAllergens(recipe, productLookup);
                    return (
                      <Card key={recipe.id}>
                        <CardContent className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-center">
                          <div>
                            <p className="font-medium">{recipe.name}</p>
                            <p className="text-sm text-muted-foreground">
                              {recipe.items.length} {recipe.items.length === 1 ? "item" : "items"}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-1">
                            <AllergenList allergens={summary.allergens} />
                            {summary.unknown ? <AllergenUnknownChip /> : null}
                          </div>
                          <div className="flex gap-2">
                            <Button
                              variant="outline"
                              aria-label={`Edit ${recipe.name}`}
                              onClick={() => openRecipe(recipe)}
                            >
                              Edit
                            </Button>
                            <Button
                              variant="destructive"
                              aria-label={`Delete ${recipe.name}`}
                              onClick={() => {
                                setDeletingRecipe(recipe);
                                setError("");
                                setDialog("delete-recipe");
                              }}
                            >
                              Delete
                            </Button>
                          </div>
                        </CardContent>
                      </Card>
                    );
                  })}
                </div>
              ) : (
                <EmptyState title="No recipes yet">Add a recipe to calculate ingredient demand.</EmptyState>
              )}
            </TabsContent>
          </Tabs>
        ) : null}

        <Dialog open={dialog === "product"} onOpenChange={(open) => !open && !busy && setDialog(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{editingProduct ? "Edit product" : "Add product"}</DialogTitle>
            </DialogHeader>
            <form onSubmit={saveProduct} className="contents">
              <DialogBody className="space-y-4">
                <label className={labelClass}>
                  Name
                  <Input required value={name} onChange={(event) => setName(event.target.value)} />
                </label>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className={labelClass}>
                    Unit
                    <Input required value={unit} onChange={(event) => setUnit(event.target.value)} />
                  </label>
                  <label className={labelClass}>
                    Pack size
                    <Input
                      type="number"
                      min="0"
                      step="any"
                      value={packSize}
                      onChange={(event) => setPackSize(event.target.value)}
                    />
                  </label>
                  <label className={labelClass}>
                    Price (EUR)
                    <Input
                      type="number"
                      min="0"
                      step="0.01"
                      value={price}
                      onChange={(event) => setPrice(event.target.value)}
                    />
                  </label>
                  <label className={labelClass}>
                    Supplier
                    <Select required value={supplierId} onValueChange={setSupplierId}>
                      <SelectTrigger>
                        <SelectValue placeholder="Choose supplier" />
                      </SelectTrigger>
                      <SelectContent>
                        {suppliers.map((supplier) => (
                          <SelectItem key={supplier.id} value={supplier.id}>
                            {supplier.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                </div>
                <div className="space-y-3">
                  <label className="flex items-center gap-2 text-sm font-medium">
                    <Checkbox checked={unknown} onCheckedChange={(checked) => setUnknown(checked === true)} />
                    Allergen data unknown
                  </label>
                  {!unknown ? (
                    <div className="space-y-2">
                      {ALLERGENS.map(([code, allergenName]) => (
                        <div key={code} className="grid grid-cols-[1fr_1fr] items-center gap-3">
                          <label className="flex items-center gap-2 text-sm">
                            <Checkbox
                              checked={Boolean(allergenValues[code])}
                              onCheckedChange={(checked) =>
                                setAllergenValues((current) => {
                                  const next = { ...current };
                                  if (checked) next[code] ??= "CONTAINS";
                                  else delete next[code];
                                  return next;
                                })
                              }
                            />
                            {code} {allergenName}
                          </label>
                          <Select
                            value={allergenValues[code] ?? "CONTAINS"}
                            disabled={!allergenValues[code]}
                            onValueChange={(value) =>
                              setAllergenValues((current) => ({ ...current, [code]: value as AllergenPresence }))
                            }
                          >
                            <SelectTrigger aria-label={`${allergenName} presence`}>
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="CONTAINS">Contains</SelectItem>
                              <SelectItem value="MAY_CONTAIN">May contain</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
                {actionError}
              </DialogBody>
              <DialogFooter>
                <Button disabled={busy}>{busy ? "Saving…" : "Save product"}</Button>
                <Button type="button" variant="outline" disabled={busy} onClick={() => setDialog(null)}>
                  Cancel
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>

        <Dialog open={dialog === "recipe"} onOpenChange={(open) => !open && !busy && setDialog(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{editingRecipe ? "Edit recipe" : "Add recipe"}</DialogTitle>
            </DialogHeader>
            <form onSubmit={saveRecipe} className="contents">
              <DialogBody className="space-y-4">
                <label className={labelClass}>
                  Name
                  <Input required value={name} onChange={(event) => setName(event.target.value)} />
                </label>
                {items.map((item, index) => {
                  const product = productLookup.get(item.productId);
                  const unitName = product ? ("baseUnit" in product ? product.baseUnit : product.unit) : item.unit;
                  return (
                    <div
                      key={item.key}
                      className="grid gap-3 rounded-md border p-3 sm:grid-cols-[1fr_150px_auto] sm:items-start"
                    >
                      <div>
                        <ProductPicker
                          value={{ productId: item.productId, productName: item.productName }}
                          findProduct={findPickerProduct}
                          ownProducts={products}
                          suppliers={suppliers}
                          search={searchProducts}
                          loadProducts={loadProducts}
                          onChoose={(choice) => chooseProduct(index, choice)}
                          onChange={() => clearProduct(index)}
                        />
                        {item.productId === "" ? (
                          <p className="mt-1 text-xs text-destructive">Choose a product for this item.</p>
                        ) : null}
                      </div>
                      <div className={labelClass}>
                        Quantity per portion
                        <Input
                          aria-label="Quantity per portion"
                          aria-describedby={`${item.key}-unit`}
                          type="text"
                          inputMode="decimal"
                          autoComplete="off"
                          value={item.qtyPerPortion}
                          onChange={(event) =>
                            setItems((rows) =>
                              rows.map((row, rowIndex) =>
                                rowIndex === index ? { ...row, qtyPerPortion: event.target.value } : row,
                              ),
                            )
                          }
                        />
                        <span id={`${item.key}-unit`} className="text-xs text-muted-foreground">
                          {unitName || "Unit from product"}
                        </span>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => setItems((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}
                      >
                        Remove
                      </Button>
                    </div>
                  );
                })}
                <Button
                  type="button"
                  variant="outline"
                  onClick={() =>
                    setItems((rows) => [
                      ...rows,
                      { productId: "", productName: "", unit: "", qtyPerPortion: "", key: newRowKey() },
                    ])
                  }
                >
                  Add item
                </Button>
                {actionError}
              </DialogBody>
              <DialogFooter>
                <Button disabled={busy}>{busy ? "Saving…" : "Save recipe"}</Button>
                <Button type="button" variant="outline" disabled={busy} onClick={() => setDialog(null)}>
                  Cancel
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>

        <Dialog
          open={dialog === "delete-product" || dialog === "delete-recipe"}
          onOpenChange={(open) => !open && !busy && setDialog(null)}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete {dialog === "delete-product" ? "product" : "recipe"}?</DialogTitle>
            </DialogHeader>
            <DialogBody>
              <p>Delete {dialog === "delete-product" ? deletingProduct?.name : deletingRecipe?.name}?</p>
              {actionError}
            </DialogBody>
            <DialogFooter>
              <Button
                variant="destructive"
                disabled={busy}
                onClick={dialog === "delete-product" ? removeProduct : removeRecipe}
              >
                Delete
              </Button>
              <Button variant="outline" disabled={busy} onClick={() => setDialog(null)}>
                Cancel
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </AppShell>
  );
}

export function ProductsPage() {
  return <ProductsPageContent />;
}
