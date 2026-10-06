"use client";

import React from "react";
import { useWallet } from "@/context/WalletContext";
import { Bot, Wallet, Settings, ExternalLink, Network, ShieldCheck } from "lucide-react";

interface NavbarProps {
  onOpenSettings: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({ onOpenSettings }) => {
  const { address, isConnected, isConnecting, connectWallet, disconnectWallet, chainName, balance } = useWallet();

  const formatAddress = (addr: string) => `${addr.slice(0, 6)}...${addr.slice(-4)}`;

  return (
    <header className="sticky top-0 z-40 border-b border-border/80 bg-background/80 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-purple-600 to-cyan-500 p-0.5 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <div className="h-full w-full bg-background rounded-[10px] flex items-center justify-center">
              <Bot className="h-5 w-5 text-indigo-400 animate-pulse" />
            </div>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-lg text-white tracking-tight">Web3 AI Agent</span>
              <span className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                EVM Executor
              </span>
            </div>
            <p className="text-xs text-gray-400 hidden sm:block">AI-Powered Smart Contract & On-Chain Assistant</p>
          </div>
        </div>

        {/* Right actions */}
        <div className="flex items-center gap-3">
          {/* Network indicator */}
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-card border border-border text-xs text-gray-300">
            <div className="h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
            <Network className="h-3.5 w-3.5 text-gray-400" />
            <span>{chainName}</span>
          </div>

          {/* Wallet connect */}
          {isConnected && address ? (
            <div className="flex items-center gap-2 bg-card border border-border rounded-lg p-1">
              <div className="px-3 py-1 text-xs text-gray-300 hidden md:flex items-center gap-1 font-mono">
                <span className="text-indigo-400 font-semibold">{balance}</span> ETH
              </div>
              <button
                onClick={disconnectWallet}
                className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-cardHover hover:bg-red-500/10 hover:text-red-400 text-xs font-mono text-gray-200 transition-colors border border-border"
                title="Click to disconnect"
              >
                <div className="h-2 w-2 rounded-full bg-emerald-400" />
                <span>{formatAddress(address)}</span>
              </button>
            </div>
          ) : (
            <button
              onClick={connectWallet}
              disabled={isConnecting}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white text-xs font-medium shadow-md shadow-indigo-500/25 transition-all hover:scale-[1.02] active:scale-[0.98]"
            >
              <Wallet className="h-4 w-4" />
              <span>{isConnecting ? "Đang kết nối..." : "Kết nối Ví"}</span>
            </button>
          )}

          {/* Settings button */}
          <button
            onClick={onOpenSettings}
            className="p-2 rounded-lg bg-card hover:bg-cardHover border border-border text-gray-400 hover:text-white transition-colors"
            title="Cài đặt hệ thống & API Key"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </div>
    </header>
  );
};

