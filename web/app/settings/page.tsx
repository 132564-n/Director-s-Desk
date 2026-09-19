import Link from "next/link";
import { TeamSettings } from "@/components/team-settings";

export default function SettingsPage() {
  return <main className="settings-page">
    <nav><Link href="/">← 返回导演组群聊</Link><span>全局团队 API 配置</span></nav>
    <TeamSettings />
  </main>;
}
