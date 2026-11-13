import { useMemo, useState } from "react";

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
import type { Allergen, AllergenPresence, OwnProduct, Product, Recipe, RecipeItem, Supplier } from "@/types";
import { recipeAllergens } from "@/pages/products/recipe-allergens";

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

async function loadData(api: ReturnType<typeof useApi>) {
  const [ownProducts, suppliers, recipes, catalog] = await Promise.all([
    api.listOwnProducts(),
    api.listSuppliers(),
    api.listRecipes(),
    api.searchProducts(""),
  ]);
  return { ownProducts, suppliers, recipes, catalog };
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
  const [items, setItems] = useState<Array<Omit<RecipeItem, "qtyPerPortion"> & { qtyPerPortion: string }>>([]);
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
    setDialog("product");
  }
  function openRecipe(recipe: Recipe | null = null) {
    setEditingRecipe(recipe);
    setName(recipe?.name ?? "");
    setItems(recipe ? recipe.items.map((item) => ({ ...item, qtyPerPortion: String(item.qtyPerPortion) })) : []);
    setError("");
    setDialog("recipe");
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
      setDialog(null);
      state.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }
  async function saveRecipe(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const quantities = items.map((item) => Number(item.qtyPerPortion));
    if (quantities.some((quantity) => !Number.isFinite(quantity) || quantity <= 0)) {
      setError("Each quantity per portion must be greater than 0.");
      return;
    }
    setBusy(true);
    setError("");
    const resolved = items.map((item, index) => {
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
      setDialog(null);
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
      setDialog(null);
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
      setDialog(null);
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
          <h1 className="text-2xl font-semibold">Products</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Review products available to this kitchen and their purchasing data.
          </p>
        </header>
        {state.status === "loading" ? <LoadingState label="Loading products and recipes" /> : null}
        {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
        {state.status === "ready" ? (
          <Tabs defaultValue="products">
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
                      key={index}
                      className="grid gap-2 rounded-md border p-3 sm:grid-cols-[1fr_120px_auto] sm:items-end"
                    >
                      <label className={labelClass}>
                        Product
                        <Select
                          required
                          value={item.productId}
                          onValueChange={(id) =>
                            setItems((rows) =>
                              rows.map((row, rowIndex) => {
                                if (rowIndex !== index) return row;
                                const selected = productLookup.get(id);
                                return {
                                  ...row,
                                  productId: id,
                                  productName: selected ? productName(selected) : "",
                                  unit: selected ? ("baseUnit" in selected ? selected.baseUnit : selected.unit) : "",
                                };
                              }),
                            )
                          }
                        >
                          <SelectTrigger className="w-full">
                            <SelectValue placeholder="Choose product" />
                          </SelectTrigger>
                          <SelectContent>
                            {[...products, ...catalog].map((option) => (
                              <SelectItem key={option.id} value={option.id}>
                                {productName(option)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </label>
                      <label className={labelClass}>
                        Quantity per portion
                        <Input
                          type="text"
                          required
                          min="0.000001"
                          step="any"
                          value={item.qtyPerPortion || ""}
                          onChange={(event) =>
                            setItems((rows) =>
                              rows.map((row, rowIndex) =>
                                rowIndex === index ? { ...row, qtyPerPortion: event.target.value } : row,
                              ),
                            )
                          }
                        />
                        <span className="text-xs text-muted-foreground">{unitName || "Unit from product"}</span>
                      </label>
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
                    setItems((rows) => [...rows, { productId: "", productName: "", unit: "", qtyPerPortion: "" }])
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
