import { useApi } from "@/api";
import type { Api } from "@/api/types";
import { useT } from "@/lib/i18n";

/**
 * A quiet "MongoDB Atlas" mark on what the gateway read from Atlas. `of` is the Api method the
 * data came through: on the mock, or while the gateway does not serve it, nothing is shown, so
 * the mark never claims Atlas for sample figures. `what` says what Atlas did, for the tooltip.
 */
export function AtlasMark({ of, what }: { of: keyof Api; what: string }) {
  const t = useT();
  const { live } = useApi();
  if (!live?.has(of)) return null;
  return <AtlasMarkLabel title={t(what)} />;
}

export function AtlasMarkLabel({ title }: { title?: string }) {
  return (
    <span className="actor-box shrink-0" data-actor="machine" data-testid="atlas-mark" title={title}>
      MongoDB Atlas
    </span>
  );
}
