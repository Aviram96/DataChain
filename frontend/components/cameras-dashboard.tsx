"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { networkErrorMessage } from "@/lib/api";
import {
  CamerasApiError,
  listCameras,
  type CameraPublic,
} from "@/lib/cameras-api";

import { CameraCard } from "./camera-card";
import { useToast } from "./toast-provider";

const PAGE_SIZE = 10;

export function CamerasDashboard() {
  const { showToast } = useToast();
  const [cameras, setCameras] = useState<CameraPublic[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const loadCameras = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listCameras(1, PAGE_SIZE);
      setCameras(data.items);
      setTotal(data.total);
    } catch (error) {
      if (error instanceof CamerasApiError) {
        showToast(error.message, "error");
      } else {
        showToast(networkErrorMessage(), "error");
      }
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void loadCameras();
  }, [loadCameras]);

  const hasMore = total > cameras.length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-white">Cameras</h1>
          <p className="text-sm text-slate-400">
            {loading
              ? "Loading…"
              : total === 0
                ? "No cameras yet."
                : `${total} camera${total === 1 ? "" : "s"}`}
          </p>
        </div>
        <Link
          href="/cameras/new"
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
        >
          Add camera
        </Link>
      </div>

      {loading ? (
        <p className="text-slate-400">Loading cameras…</p>
      ) : cameras.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-700 p-8 text-center text-slate-400">
          Add your first camera to start monitoring streams.
        </p>
      ) : (
        <CamerasGrid cameras={cameras} />
      )}

      {hasMore ? (
        <p className="text-sm text-slate-500">
          Showing {cameras.length} of {total} cameras.
        </p>
      ) : null}
    </div>
  );
}

function CamerasGrid({ cameras }: { cameras: CameraPublic[] }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {cameras.map((camera) => (
        <CameraCard key={camera.id} camera={camera} />
      ))}
    </div>
  );
}
