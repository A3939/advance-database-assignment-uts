import DataPage from "@/components/data-page";
import { dataTab } from "@/services/data-navigation";
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <DataPage initialTab={dataTab((await searchParams).tab)} />;
}
