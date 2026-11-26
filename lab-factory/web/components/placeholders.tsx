"use client";

// Stand-ins for the views later tasks build. Shell.tsx imports each one on its own line, so a
// task that builds a view replaces one import line and deletes its stand-in here.

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

export function SkillsPage(_props: { skill?: string }) {
  return <Placeholder title="Skills" />;
}

export function ConnectorsPage() {
  return <Placeholder title="Connectors" />;
}

export function AgentsPage() {
  return <Placeholder title="Connect your agent" />;
}

export function Workspace(_props: { projectId: string; experimentId: string }) {
  return <Placeholder title="Experiment" />;
}

function Placeholder({ title }: { title: string }) {
  return (
    <div className="page">
      <h1>{title}</h1>
    </div>
  );
}
