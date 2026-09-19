"use client";

import { ApprovalsList } from "@/components/ApprovalsList";
import { PortfolioSummary } from "@/components/PortfolioSummary";
import { PriceChart } from "@/components/PriceChart";

/** The home route: approvals queue first (the product's reason to exist), then portfolio, then a chart. */
export function HomeView() {
  return (
    <>
      <ApprovalsList />
      <PortfolioSummary />
      <PriceChart />
    </>
  );
}
