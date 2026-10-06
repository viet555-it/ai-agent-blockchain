"use client";

import React, { useState, useEffect } from "react";
import { ShieldCheck, ShieldAlert, Sliders, History, Check, AlertCircle, RefreshCw } from "lucide-react";
import { GuardrailPolicies, AuditLog, fetchGuardrailPolicies, updateGuardrailPolicies, fetchAuditLogs } from "@/services/api";

export const GuardrailPanel: React.FC = () => {
  const [policies, setPolicies] = useState<GuardrailPolicies | null>(null);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [maxEth, setMaxEth] = useState<string>("0.1");
  const [maxToken, setMaxToken] = useState<string>("500");
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [activeTab, setActiveTab] = useState<"policies" | "logs">("policies");

  const loadData = async () => {
    try {
      setLoading(true);
      const pol = await fetchGuardrailPolicies();
      setPolicies(pol);
      setMaxEth(pol.max_eth_limit.toString());
      setMaxToken(pol.max_token_limit.toString());

      const logRes = await fetchAuditLogs();
      setLogs(logRes.logs);
    } catch (e) {
      console.error("Failed to load guardrail data:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSavePolicies = async () => {
    try {
      setLoading(true);
      const updated = await updateGuardrailPolicies(parseFloat(maxEth), parseFloat(maxToken));
      setPolicies(updated.current_policies);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-4 rounded-2xl bg-card border border-border">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-border/80">
        <div className="flex items-center gap-2">
          <div className="p-1 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <ShieldCheck className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-xs font-semibold text-white">Guardrail & Policy Engine</h3>
            <p className="text-[10px] text-gray-400">Security limits & Human-in-the-loop</p>
          </div>
        </div>

        {/* Tab switcher */}
        <div className="flex bg-background rounded-lg p-0.5 border border-border">
          <button
            onClick={() => setActiveTab("policies")}
            className={`px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${
              activeTab === "policies" ? "bg-card text-white" : "text-gray-400 hover:text-gray-200"
            }`}
          >
            Chính sách
          </button>
          <button
            onClick={() => {
              setActiveTab("logs");
              loadData();
            }}
            className={`px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${
              activeTab === "logs" ? "bg-card text-white" : "text-gray-400 hover:text-gray-200"
            }`}
          >
            Audit Logs ({logs.length})
          </button>
        </div>
      </div>

      {activeTab === "policies" ? (
        <div className="mt-3 space-y-3 text-xs">
          <div>
            <label className="text-[11px] text-gray-400 block mb-1">Hạn mức tối đa mỗi giao dịch ETH:</label>
            <div className="flex gap-2">
              <input
                type="number"
                step="0.01"
                value={maxEth}
                onChange={(e) => setMaxEth(e.target.value)}
                className="flex-1 px-2.5 py-1.5 rounded-lg bg-background border border-border text-white text-xs font-mono focus:outline-none focus:border-indigo-500"
              />
              <span className="self-center font-mono text-gray-400 text-xs">ETH</span>
            </div>
          </div>

          <div>
            <label className="text-[11px] text-gray-400 block mb-1">Hạn mức tối đa mỗi giao dịch Token (USDC/LINK):</label>
            <div className="flex gap-2">
              <input
                type="number"
                step="10"
                value={maxToken}
                onChange={(e) => setMaxToken(e.target.value)}
                className="flex-1 px-2.5 py-1.5 rounded-lg bg-background border border-border text-white text-xs font-mono focus:outline-none focus:border-indigo-500"
              />
              <span className="self-center font-mono text-gray-400 text-xs">Tokens</span>
            </div>
          </div>

          {/* Safety Badges */}
          <div className="pt-2 border-t border-border/60 grid grid-cols-2 gap-2 text-[10px] text-gray-400 font-mono">
            <div className="p-1.5 rounded bg-background border border-border flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              <span>Human Approval: ON</span>
            </div>
            <div className="p-1.5 rounded bg-background border border-border flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full bg-cyan-400" />
              <span>Dry-Run Simulation: ON</span>
            </div>
          </div>

          <button
            onClick={handleSavePolicies}
            disabled={loading}
            className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow transition-all"
          >
            {saved ? (
              <>
                <Check className="h-3.5 w-3.5" />
                <span>Đã cập nhật chính sách!</span>
              </>
            ) : (
              <span>Lưu chính sách Guardrail</span>
            )}
          </button>
        </div>
      ) : (
        <div className="mt-3 space-y-2 max-h-56 overflow-y-auto pr-1">
          {logs.length === 0 ? (
            <p className="text-[11px] text-gray-500 text-center py-4">Chưa có giao dịch nào được ghi log kiểm duyệt.</p>
          ) : (
            logs.map((item, idx) => (
              <div key={idx} className="p-2 rounded-lg bg-background border border-border/70 text-[10px] font-mono space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">{item.tx_type}</span>
                  <span className={item.status === "ALLOWED" ? "text-emerald-400 font-bold" : "text-red-400 font-bold"}>
                    {item.status}
                  </span>
                </div>
                <div className="text-gray-300 truncate">Target: {item.target}</div>
                {item.value_eth && <div className="text-indigo-300">Amount: {item.value_eth} ETH</div>}
                {item.block_reason && <div className="text-red-400 font-sans">{item.block_reason}</div>}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};

