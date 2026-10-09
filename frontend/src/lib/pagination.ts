// Seitenzahlen für die Blätterleiste: 1 … 4 5 6 … 20

export type PageToken = number | "gap";

export function totalPages(total: number, pageSize: number): number {
  if (pageSize <= 0) return 1;
  return Math.max(1, Math.ceil(total / pageSize));
}

export function pageTokens(current: number, pages: number): PageToken[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const set = new Set<number>([1, pages, current - 1, current, current + 1]);
  const nums = [...set].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const out: PageToken[] = [];
  for (let i = 0; i < nums.length; i++) {
    if (i > 0 && nums[i] - nums[i - 1] > 1) out.push("gap");
    out.push(nums[i]);
  }
  return out;
}
