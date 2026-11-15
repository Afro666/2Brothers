import { useApi } from "@/api";
import type { Api } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { useT } from "@/lib/i18n";

/**
 * Gateway mode only: marks what still comes from the mock because the gateway has no
 * route for it. Renders nothing on the mock, and nothing once the gateway serves `of`.
 */
export function SampleData({ of }: { of: keyof Api }) {
  const t = useT();
  const { live } = useApi();
  if (!live || live.has(of)) return null;
  return (
    <Badge
      variant="outline"
      title={t("Sample figures, not your kitchen's own: this part of the demo is not connected yet.")}
    >
      {t("Sample data")}
    </Badge>
  );
}
