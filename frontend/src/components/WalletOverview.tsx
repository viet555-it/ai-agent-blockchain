"use client";

import React, { useState } from "react";
import { useWallet } from "@/context/WalletContext";
import { Copy, Check, ExternalLink, Coins, Layers, ArrowDownLeft, ArrowUpRight } from "lucide-react";

export const WalletOverview: React.FC = () => {
  const { address, isConnected, chainName, chainId, balance } = useWallet();
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    if (address) {
      navigator.clipboard.writeText(address);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const getExplorerUrl = () => {
    if (!address) return "#";
    if (chainId === 11155111) {
      return `https://sepolia.etherscan.io/address/${address}`;
    }
    return `https://etherscan.io/address/${address}`;
  };

  if (!isConnected || !address) {
    return (
      <div className="p-5 rounded-2xl bg-card border border-border flex flex-col items-center justify-center text-center">
        <div className="h-12 w-12 rounded-full bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 mb-3">
          <Coins className="h-6 w-6" />
        </div>
        <h3 className="text-sm font-semibold text-white">Chưa kết nối ví</h3>
        <p className="text-xs text-gray-400 mt-1 max-w-xs">
          Kết nối ví Web3 để xem số dư thời gian thực và ký các giao dịch do AI Agent đề xuất.
        </p>
      </div>
    );
  }

  return (
    <div className="p-5 rounded-2xl bg-gradient-to-br from-card via-card to-indigo-950/20 border border-border">
      <div className="flex items-center justify-between pb-3 border-b border-border/80">
        <div className="flex items-center gap-2">
          <div className="h-2.5 w-2.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">{chainName}</span>
        </div>
        <a
          href={getExplorerUrl()}
          target="_blank"
          rel="noreferrer"
          className="text-gray-400 hover:text-indigo-400 transition-colors p-1"
          title="Xem trên Explorer"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>

      <div className="mt-4">
        <span className="text-[11px] text-gray-400">Số dư khả dụng</span>
        <div className="flex items-baseline gap-2 mt-0.5">
          <span className="text-2xl font-bold font-mono text-white tracking-tight">{balance}</span>
          <span className="text-xs font-semibold text-indigo-400 uppercase">ETH</span>
        </div>
      </div>

      <div className="mt-4 p-2.5 rounded-xl bg-background/60 border border-border/60 flex items-center justify-between">
        <div className="flex flex-col truncate pr-2">
          <span className="text-[10px] text-gray-400">Địa chỉ ví của bạn</span>
          <span className="text-xs font-mono text-gray-200 truncate">{address}</span>
        </div>
        <button
          onClick={handleCopy}
          className="p-1.5 rounded-lg bg-card hover:bg-cardHover border border-border text-gray-400 hover:text-white transition-colors"
          title="Sao chép địa chỉ"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>

      {/* Asset quick breakdown */}
      <div className="mt-4 pt-3 border-t border-border/60 grid grid-cols-2 gap-2 text-xs">
        <div className="p-2 rounded-lg bg-card border border-border/60">
          <span className="text-[10px] text-gray-400 block">Testnet USDC</span>
          <span className="font-mono text-white font-medium">100.00</span>
        </div>
        <div className="p-2 rounded-lg bg-card border border-border/60">
          <span className="text-[10px] text-gray-400 block">AI Agent NFTs</span>
          <span className="font-mono text-white font-medium">2 Items</span>
        </div>
      </div>
    </div>
  );
};

