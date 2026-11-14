import { useApi } from "@/api";
import type { Api } from "@/api/types";
import { Badge } from "@/components/ui/badge";

/**
 * Gateway mode only: marks what still comes from the mock because the gateway has no
 * route for it. Renders nothing on the mock, and nothing once the gateway serves `of`.
 */
export function SampleData({ of }: { of: keyof Api }) {
  const { live } = useApi();
  if (!live || live.has(of)) return null;
  return (
    <Badge
      variant="outline"
      title="The gateway does not serve this yet. These are sample figures, not the kitchen's own."
    >
      Sample data
    </Badge>
  );
}
