import { ClientProvider } from "../components/ClientContext.tsx";
import { Shell } from "../components/Shell.tsx";

export default function Page() {
  return (
    <ClientProvider>
      <Shell />
    </ClientProvider>
  );
}
