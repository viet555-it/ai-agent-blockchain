"use client";

import React from "react";
import { Coins, Send, Palette, Activity, Zap } from "lucide-react";

interface QuickActionsProps {
  onSelectAction: (prompt: string) => void;
}

export const QuickActions: React.FC<QuickActionsProps> = ({ onSelectAction }) => {
  const actions = [
    {
      label: "Kiểm tra số dư ví",
      prompt: "Kiểm tra số dư ETH và token trong ví của tôi",
      icon: Coins,
      color: "text-amber-400",
    },
    {
      label: "Gửi 0.001 ETH",
      prompt: "Gửi 0.001 ETH tới địa chỉ 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
      icon: Send,
      color: "text-indigo-400",
    },
    {
      label: "Mint AI Agent NFT",
      prompt: "Mint 1 NFT mẫu Web3 AI Agent về địa chỉ ví của tôi",
      icon: Palette,
      color: "text-purple-400",
    },
    {
      label: "Thông tin mạng & Block",
      prompt: "Lấy thông tin mạng Blockchain hiện tại và block mới nhất",
      icon: Activity,
      color: "text-cyan-400",
    },
  ];

  return (
    <div className="p-4 rounded-2xl bg-card border border-border">
      <div className="flex items-center gap-2 mb-3">
        <Zap className="h-4 w-4 text-amber-400" />
        <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">Thao tác nhanh</span>
      </div>
      <div className="flex flex-col gap-2">
        {actions.map((act, idx) => {
          const Icon = act.icon;
          return (
            <button
              key={idx}
              onClick={() => onSelectAction(act.prompt)}
              className="flex items-center gap-2.5 p-2.5 rounded-xl bg-cardHover/50 hover:bg-cardHover border border-border/60 hover:border-indigo-500/40 text-left transition-all group"
            >
              <div className={`p-1.5 rounded-lg bg-background border border-border/80 ${act.color} group-hover:scale-105 transition-transform`}>
                <Icon className="h-3.5 w-3.5" />
              </div>
              <span className="text-xs text-gray-300 group-hover:text-white transition-colors">{act.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
};

