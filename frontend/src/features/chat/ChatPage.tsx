import { useUi } from "@/stores/ui";
import { ChatPane } from "./ChatPane";

export default function ChatPage() {
  const workspaceId = useUi((s) => s.workspaceId);
  return <ChatPane workspaceId={workspaceId} />;
}
