"use client";

// Stand-ins for the views later tasks build. Shell.tsx imports each one on its own line, grouped
// by task. Later tasks change only their own import lines in Shell.tsx and leave this file alone;
// Task 17 deletes it once nothing imports from it.

// Task 9 views

export function LabHome() {
  return <Placeholder title="Lab home" />;
}

export function ProjectPage(_props: { projectId: string }) {
  return <Placeholder title="Project" />;
}

export function LabPage() {
  return <Placeholder title="Lab instruments and documents" />;
}

export function SettingsPage() {
  return <Placeholder title="Lab settings" />;
}

// Task 10 views

export function SkillsPage(_props: { skill?: string }) {
  return <Placeholder title="Skills" />;
}

export function ConnectorsPage() {
  return <Placeholder title="Connectors" />;
}

export function AgentsPage() {
  return <Placeholder title="Connect your agent" />;
}

// Task 11 views

export function Workspace(_props: { projectId: string; experimentId: string }) {
  return <Placeholder title="Experiment" />;
}

// Shared

function Placeholder({ title }: { title: string }) {
  return (
    <div className="page">
      <h1>{title}</h1>
    </div>
  );
}
