import type { Metadata } from "next";

import { ReviewBoard } from "@/components/ReviewBoard";

export const metadata: Metadata = {
  title: "教师复核 · SynapseMind 突触智学",
  description: "只读的卡点卡异议队列：逐条判断，导出 CSV。",
};

export default function ReviewPage() {
  return <ReviewBoard />;
}