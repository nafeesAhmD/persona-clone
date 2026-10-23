"use client";

import { useState } from "react";

import {
  Badge,
  ErrorNote,
  Loading,
  PageHeader,
  Pagination,
  Table,
  buttonClass,
  formatDate,
  inputClass,
  useAdminData,
} from "@/components/admin/ui";
import { adminApi } from "@/lib/adminApi";

const LIMIT = 20;
const CATEGORIES = ["llm", "voice", "avatar", "storage", "vector_store", "embedding", "ingestion", "internal"];

export default function AdminErrorsPage() {
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState("");
  const [statusCode, setStatusCode] = useState("");
  const [endpointInput, setEndpointInput] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const { data, error, loading } = useAdminData(
    () => adminApi.errors({ page, limit: LIMIT, category, status_code: statusCode, endpoint }),
    [page, category, statusCode, endpoint],
  );

  return (
    <>
      <PageHeader
        title="Error Log"
        description="Server and provider errors (ERROR_LOG_RETENTION_DAYS). Ids in paths are masked; request bodies are never stored."
      />
      <form
        className="mb-4 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setEndpoint(endpointInput.trim());
        }}
      >
        <select aria-label="Category" className={inputClass} value={category} onChange={(e) => { setPage(1); setCategory(e.target.value); }}>
          <option value="">All categories</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select aria-label="Status code" className={inputClass} value={statusCode} onChange={(e) => { setPage(1); setStatusCode(e.target.value); }}>
          <option value="">Any status</option>
          {["429", "500", "502", "503", "504"].map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input
          aria-label="Endpoint"
          className={`${inputClass} min-w-48 flex-1`}
          placeholder="Endpoint contains…"
          maxLength={100}
          value={endpointInput}
          onChange={(e) => setEndpointInput(e.target.value)}
        />
        <button type="submit" className={buttonClass}>Filter</button>
      </form>
      <ErrorNote message={error} />
      {loading && !data && <Loading />}
      {data && (
        <>
          <Table head={["When", "Category", "Status", "Endpoint", "Error", "Location"]} empty={data.items.length === 0}>
            {data.items.map((e) => (
              <tr key={e.id}>
                <td className="whitespace-nowrap px-3 py-2 text-muted">{formatDate(e.created_at)}</td>
                <td className="px-3 py-2"><Badge>{e.category}</Badge></td>
                <td className={`px-3 py-2 ${e.status_code >= 500 ? "text-rose-300" : "text-amber-300"}`}>{e.status_code}</td>
                <td className="px-3 py-2 font-mono text-xs">{e.method ? `${e.method} ` : ""}{e.endpoint ?? "(background)"}</td>
                <td className="max-w-xs px-3 py-2 text-xs">
                  <span className="block text-white">{e.error_type}</span>
                  {e.message && <span className="text-muted">{e.message}</span>}
                </td>
                <td className="px-3 py-2 font-mono text-xs text-muted">{e.location ?? "—"}</td>
              </tr>
            ))}
          </Table>
          <Pagination page={data.page} limit={data.limit} total={data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}
