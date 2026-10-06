"use client";

import React, { useState, useEffect } from "react";
import { X, Key, Globe, Check, Server } from "lucide-react";
import { useWallet } from "@/context/WalletContext";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const { chainId, switchNetwork } = useWallet();
  const [apiKey, setApiKey] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("openai_api_key") || "";
    setApiKey(stored);
  }, [isOpen]);

  const handleSave = () => {
    localStorage.setItem("openai_api_key", apiKey.trim());
    setSaved(true);
    setTimeout(() => {
      setSaved(false);
      onClose();
    }, 800);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="relative w-full max-w-md rounded-2xl bg-card border border-border p-6 shadow-2xl">
        <div className="flex items-center justify-between pb-4 border-b border-border">
          <h3 className="text-base font-semibold text-white">Cấu hình Hệ thống & AI</h3>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-gray-400 hover:text-white hover:bg-cardHover transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-4 space-y-4 text-xs">
          {/* OpenAI API Key */}
          <div>
            <label className="flex items-center gap-1.5 font-medium text-gray-300 mb-1.5">
              <Key className="h-3.5 w-3.5 text-indigo-400" />
              <span>OpenAI API Key (Tùy chọn)</span>
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-proj-..."
              className="w-full px-3 py-2 rounded-xl bg-background border border-border text-gray-100 placeholder-gray-500 focus:outline-none focus:border-indigo-500 font-mono text-xs"
            />
            <p className="text-[11px] text-gray-500 mt-1">
              Khóa API được lưu cục bộ trên trình duyệt của bạn và gửi an toàn tới Backend. Nếu để trống, hệ thống sẽ dùng heuristic fallback.
            </p>
          </div>

          {/* Network Selection */}
          <div>
            <label className="flex items-center gap-1.5 font-medium text-gray-300 mb-1.5">
              <Globe className="h-3.5 w-3.5 text-cyan-400" />
              <span>Mạng Blockchain (EVM Network)</span>
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => switchNetwork(11155111)}
                className={`p-2.5 rounded-xl border text-left transition-all ${
                  chainId === 11155111
                    ? "bg-indigo-600/20 border-indigo-500 text-white"
                    : "bg-background border-border text-gray-400 hover:text-gray-200"
                }`}
              >
                <div className="font-semibold text-xs">Sepolia Testnet</div>
                <div className="text-[10px] text-gray-400">Chain ID: 11155111</div>
              </button>

              <button
                type="button"
                onClick={() => switchNetwork(31337)}
                className={`p-2.5 rounded-xl border text-left transition-all ${
                  chainId === 31337
                    ? "bg-indigo-600/20 border-indigo-500 text-white"
                    : "bg-background border-border text-gray-400 hover:text-gray-200"
                }`}
              >
                <div className="font-semibold text-xs">Hardhat / Local</div>
                <div className="text-[10px] text-gray-400">Chain ID: 31337</div>
              </button>
            </div>
          </div>

          {/* Backend Info */}
          <div className="p-3 rounded-xl bg-background border border-border/80 text-gray-400 space-y-1">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <Server className="h-3.5 w-3.5 text-emerald-400" />
                Backend API URL:
              </span>
              <span className="font-mono text-gray-300 text-[11px]">http://127.0.0.1:8000</span>
            </div>
            <div className="flex items-center justify-between">
              <span>Trạng thái:</span>
              <span className="text-emerald-400 font-medium">Sẵn sàng</span>
            </div>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-card hover:bg-cardHover border border-border text-gray-300 text-xs font-medium transition-colors"
          >
            Đóng
          </button>
          <button
            onClick={handleSave}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-md shadow-indigo-600/30 transition-all"
          >
            {saved ? (
              <>
                <Check className="h-4 w-4" />
                <span>Đã lưu!</span>
              </>
            ) : (
              <span>Lưu thay đổi</span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

