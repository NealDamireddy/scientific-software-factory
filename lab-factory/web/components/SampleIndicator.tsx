"use client";

import { FlaskConical } from "lucide-react";

import { useClient } from "./ClientContext.tsx";

/** Always shown in sample mode, so sample data and sample activity never pass for real. */
export function SampleIndicator() {
  const { mode } = useClient();
  if (mode !== "sample") return null;
  return (
    <p className="sample-indicator">
      <FlaskConical size={16} aria-hidden="true" />
      <span>Sample data. Nothing here is saved or real.</span>
    </p>
  );
}
