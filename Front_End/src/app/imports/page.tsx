import { redirect } from "next/navigation";
import { importsDataHref } from "@/services/data-navigation";
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  redirect(importsDataHref(await searchParams));
}
