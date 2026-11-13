import { useParams } from "@tanstack/react-router";
import { ScreenPage } from "@/pages/screen";
export function OrderDetailPage() {
  const { orderId } = useParams({ from: "/orders/$orderId" });
  return (
    <ScreenPage
      title={`Order ${orderId}`}
      description="Inspect the order lines, totals, status, and decision history."
      activeId="orders"
    />
  );
}
