import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";
import { Spinner } from "./Spinner";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => string;
  loading?: boolean;
  error?: unknown;
  empty?: string;
  onRowClick?: (row: T) => void;
}

export function Table<T>({ columns, rows, rowKey, loading, error, empty, onRowClick }: Props<T>) {
  const { t } = useTranslation();
  return (
    <div className="glass overflow-hidden rounded-2xl">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/10 text-left text-[11px] uppercase tracking-wider text-fog-500">
              {columns.map((c) => (
                <th key={c.key} className={"px-4 py-3 font-medium " + (c.className ?? "")}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-10 text-center">
                  <Spinner className="mx-auto" />
                </td>
              </tr>
            )}
            {!loading && error != null && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-red-300">
                  {error instanceof Error ? error.message : t("common.loadFailed")}
                </td>
              </tr>
            )}
            {!loading && !error && rows?.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-fog-700">
                  {empty ?? t("common.empty")}
                </td>
              </tr>
            )}
            {!loading &&
              !error &&
              rows?.map((r) => (
                <tr
                  key={rowKey(r)}
                  className={"border-b border-white/5 last:border-0 hover:bg-white/[0.03] " + (onRowClick ? "cursor-pointer" : "")}
                  onClick={onRowClick ? () => onRowClick(r) : undefined}
                >
                  {columns.map((c) => (
                    <td key={c.key} className={"px-4 py-2.5 align-top " + (c.className ?? "")}>
                      {c.render(r)}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
