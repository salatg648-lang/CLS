import { useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
  type VisibilityState,
} from "@tanstack/react-table";
import {
  Search,
  SlidersHorizontal,
  ArrowDownUp,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
} from "./ui/dropdown-menu";
import { Button, Empty, useSavedState } from "./primitives";
export function DataTable<T>({
  data,
  columns,
  id,
  placeholder = "Einträge suchen …",
  toolbar,
  empty = "Noch keine Einträge",
  onRow,
}: {
  data: T[];
  columns: ColumnDef<T>[];
  id: string;
  placeholder?: string;
  toolbar?: React.ReactNode;
  empty?: string;
  onRow?: (row: T) => void;
}) {
  const [query, setQuery] = useSavedState(id + ":search", "");
  const [sorting, setSorting] = useSavedState<SortingState>(id + ":sort", []);
  const [visibility, setVisibility] = useSavedState<VisibilityState>(
    id + ":columns",
    {},
  );
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 8 });
  const table = useReactTable({
    data,
    columns,
    state: {
      globalFilter: query,
      sorting,
      columnVisibility: visibility,
      pagination,
    },
    onGlobalFilterChange: setQuery,
    onSortingChange: setSorting,
    onColumnVisibilityChange: setVisibility,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
  const count = table.getFilteredRowModel().rows.length;
  return (
    <div className="data-table">
      <div className="table-toolbar">
        <label className="table-search">
          <Search size={16} />
          <input
            aria-label={placeholder}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
          />
        </label>
        {toolbar}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" aria-label="Spalten auswählen">
              <SlidersHorizontal size={15} />
              <span className="hide-small">Ansicht</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Sichtbare Spalten</DropdownMenuLabel>
            {table
              .getAllLeafColumns()
              .filter((c) => c.getCanHide())
              .map((c) => (
                <DropdownMenuCheckboxItem
                  key={c.id}
                  checked={c.getIsVisible()}
                  onCheckedChange={(v) => c.toggleVisibility(v)}
                >
                  {typeof c.columnDef.header === "string"
                    ? c.columnDef.header
                    : c.id}
                </DropdownMenuCheckboxItem>
              ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => (
                  <th
                    key={header.id}
                    aria-sort={
                      header.column.getIsSorted() === "asc"
                        ? "ascending"
                        : header.column.getIsSorted() === "desc"
                          ? "descending"
                          : undefined
                    }
                  >
                    {header.column.getCanSort() ? (
                      <button onClick={header.column.getToggleSortingHandler()}>
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                        <ArrowDownUp size={12} />
                      </button>
                    ) : (
                      flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell, i) => (
                  <td key={cell.id}>
                    {i === 0 && onRow ? (
                      <button
                        className="cell-link"
                        onClick={() => onRow(row.original)}
                      >
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext(),
                        )}
                      </button>
                    ) : (
                      flexRender(cell.column.columnDef.cell, cell.getContext())
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!count && (
        <Empty
          title={query ? "Keine passenden Ergebnisse" : empty}
          description={
            query
              ? "Versuche einen anderen Suchbegriff oder setze den Filter zurück."
              : "Neue Einträge erscheinen hier, sobald du sie anlegst."
          }
          action={
            query ? (
              <Button variant="outline" onClick={() => setQuery("")}>
                Suche zurücksetzen
              </Button>
            ) : undefined
          }
        />
      )}
      <div className="table-footer">
        <span>
          {count} Einträge · Seite {pagination.pageIndex + 1} von{" "}
          {Math.max(1, table.getPageCount())}
        </span>
        <div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Vorherige Seite"
            disabled={!table.getCanPreviousPage()}
            onClick={() => table.previousPage()}
          >
            <ChevronLeft size={16} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Nächste Seite"
            disabled={!table.getCanNextPage()}
            onClick={() => table.nextPage()}
          >
            <ChevronRight size={16} />
          </Button>
        </div>
      </div>
    </div>
  );
}
