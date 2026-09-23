import type { Metadata } from "next";

import { StatusView } from "@/components/views/StatusView";

export const metadata: Metadata = {
  title: "Status",
};

export default function Page() {
  return <StatusView />;
}
