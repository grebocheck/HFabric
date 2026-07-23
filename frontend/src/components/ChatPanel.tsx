import { ChatWorkspace } from "./ChatWorkspace";
import { useChatPanelController, type ChatPanelProps } from "./useChatPanelController";

export type { ChatJump } from "./useChatPanelController";

export function ChatPanel(props: ChatPanelProps) {
  return <ChatWorkspace controller={useChatPanelController(props)} />;
}
