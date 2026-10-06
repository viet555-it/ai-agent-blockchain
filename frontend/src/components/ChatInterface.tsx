"use client";

import React, { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { Send, Bot, User, Loader2, Sparkles, Terminal, BookOpen, ShieldCheck, ShieldAlert } from "lucide-react";
import { ChatMessage, TransactionAction, ToolExecutionResult, RAGChunk, sendChatMessage } from "@/services/api";
import { useWallet } from "@/context/WalletContext";
import { TransactionCard } from "./TransactionCard";

interface MessageWithActions {
  message: ChatMessage;
  toolResults?: ToolExecutionResult[];
  proposedTransaction?: TransactionAction | null;
  ragContext?: RAGChunk[];
  guardrailStatus?: string;
}

interface ChatInterfaceProps {
  externalPrompt?: string;
  onClearExternalPrompt?: () => void;
  onOpenRAG?: () => void;
}

export const ChatInterface: React.FC<ChatInterfaceProps> = ({ externalPrompt, onClearExternalPrompt, onOpenRAG }) => {
  const { address, chainId } = useWallet();
  const [messages, setMessages] = useState<MessageWithActions[]>([
    {
      message: {
        role: "assistant",
        content:
          "Xin chào! Tôi là **Web3 AI Agent** 🤖⛓️\n\nTôi được trang bị hệ thống **Tool Calling + Guardrail Policy Engine + RAG Layer** theo đúng kiến trúc báo cáo:\n- 🛡️ **Guardrail Policy Engine**: Giới hạn hạn mức, kiểm duyệt Whitelist/Blacklist, bắt buộc Human-in-the-loop.\n- 📚 **RAG Context**: Tự động tra cứu đặc tả Smart Contract ABI & Solidity docs tránh hallucination.\n- 💰 **Web3 Read/Write Tools**: Kiểm tra số dư, soạn thảo giao dịch chuyển tiền ETH/ERC-20, Mint NFT an toàn.\n\n*Hãy thử gõ câu lệnh bên dưới hoặc chọn các thao tác nhanh bên phải!*",
      },
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  useEffect(() => {
    if (externalPrompt && !loading) {
      handleSendMessage(externalPrompt);
      if (onClearExternalPrompt) onClearExternalPrompt();
    }
  }, [externalPrompt]);

  const handleSendMessage = async (customText?: string) => {
    const textToSend = customText || input;
    if (!textToSend.trim() || loading) return;

    const userMsg: ChatMessage = { role: "user", content: textToSend };
    setMessages((prev) => [...prev, { message: userMsg }]);
    setInput("");
    setLoading(true);

    try {
      const apiKey = typeof window !== "undefined" ? localStorage.getItem("openai_api_key") || "" : "";
      const historyToSend = messages.map((m) => m.message);

      const res = await sendChatMessage(
        textToSend,
        address || undefined,
        chainId || 11155111,
        historyToSend,
        apiKey
      );

      const assistantMsg: ChatMessage = { role: "assistant", content: res.response };
      setMessages((prev) => [
        ...prev,
        {
          message: assistantMsg,
          toolResults: res.tool_results,
          proposedTransaction: res.proposed_transaction,
          ragContext: res.rag_context,
          guardrailStatus: res.guardrail_status,
        },
      ]);
    } catch (err: any) {
      console.error("Chat error:", err);
      setMessages((prev) => [
        ...prev,
        {
          message: {
            role: "assistant",
            content: `❌ **Đã xảy ra lỗi khi xử lý yêu cầu:**\n\`${err.message || "Lỗi không xác định"}\``,
          },
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] rounded-2xl bg-card border border-border overflow-hidden shadow-xl">
      {/* Chat header */}
      <div className="px-5 py-3.5 border-b border-border bg-card/60 backdrop-blur-sm flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
            <Sparkles className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-xs font-semibold text-white">AI Agent Conversational Hub</h2>
            <p className="text-[10px] text-gray-400">Reasoning–Action–Observation Loop & Guardrail Engine</p>
          </div>
        </div>

        {onOpenRAG && (
          <button
            onClick={onOpenRAG}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-card hover:bg-cardHover border border-border text-xs text-gray-300 hover:text-white transition-colors"
          >
            <BookOpen className="h-3.5 w-3.5 text-indigo-400" />
            <span className="text-[11px]">RAG Knowledge</span>
          </button>
        )}
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
        {messages.map((item, idx) => {
          const isUser = item.message.role === "user";
          return (
            <div key={idx} className={`flex gap-3.5 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
              {/* Avatar */}
              <div
                className={`h-8 w-8 rounded-xl shrink-0 flex items-center justify-center text-xs font-bold ${
                  isUser
                    ? "bg-indigo-600 text-white"
                    : "bg-gradient-to-tr from-purple-600 to-indigo-600 text-white shadow-md shadow-indigo-500/20"
                }`}
              >
                {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
              </div>

              {/* Message content */}
              <div className={`max-w-[85%] sm:max-w-[75%] space-y-2`}>
                <div
                  className={`p-4 rounded-2xl text-xs leading-relaxed ${
                    isUser
                      ? "bg-indigo-600 text-white rounded-tr-none font-medium"
                      : "bg-background/90 text-gray-200 border border-border/80 rounded-tl-none prose-invert"
                  }`}
                >
                  <ReactMarkdown
                    components={{
                      p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                      ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-1">{children}</ul>,
                      ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-1">{children}</ol>,
                      blockquote: ({ children }) => (
                        <blockquote className="border-l-2 border-amber-500 pl-3 py-1 my-2 bg-amber-500/10 rounded-r text-amber-200">
                          {children}
                        </blockquote>
                      ),
                      code: ({ children, className }) => (
                        <code className="bg-card px-1.5 py-0.5 rounded text-[11px] font-mono text-indigo-300 border border-border">
                          {children}
                        </code>
                      ),
                      a: ({ href, children }) => (
                        <a href={href} target="_blank" rel="noreferrer" className="text-indigo-400 underline hover:text-indigo-300">
                          {children}
                        </a>
                      ),
                    }}
                  >
                    {item.message.content || ""}
                  </ReactMarkdown>
                </div>

                {/* Badges / Tool and RAG info */}
                <div className="flex flex-wrap gap-1.5">
                  {/* Tool execution badges */}
                  {item.toolResults &&
                    item.toolResults.map((t, tIdx) => (
                      <div
                        key={tIdx}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-card border border-border/80 text-[10px] text-gray-400 font-mono"
                      >
                        <Terminal className="h-3 w-3 text-cyan-400" />
                        <span>Tool: {t.tool_name}</span>
                        <span
                          className={
                            t.status === "blocked_by_guardrail"
                              ? "text-red-400 font-bold"
                              : "text-emerald-400 font-bold"
                          }
                        >
                          ({t.status})
                        </span>
                      </div>
                    ))}

                  {/* RAG Context badge */}
                  {item.ragContext && item.ragContext.length > 0 && (
                    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-card border border-border/80 text-[10px] text-indigo-300 font-mono">
                      <BookOpen className="h-3 w-3 text-indigo-400" />
                      <span>RAG: {item.ragContext.map((c) => c.title).join(", ")}</span>
                    </div>
                  )}
                </div>

                {/* Proposed Transaction Card */}
                {item.proposedTransaction && <TransactionCard transaction={item.proposedTransaction} />}
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="flex gap-3.5">
            <div className="h-8 w-8 rounded-xl bg-gradient-to-tr from-purple-600 to-indigo-600 text-white flex items-center justify-center shrink-0">
              <Bot className="h-4 w-4" />
            </div>
            <div className="p-4 rounded-2xl rounded-tl-none bg-background/90 border border-border/80 flex items-center gap-2.5 text-xs text-gray-400">
              <Loader2 className="h-4 w-4 text-indigo-400 animate-spin" />
              <span>AI Agent đang phân tích RAG & kiểm duyệt Guardrail on-chain...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="p-4 border-t border-border bg-card/80 backdrop-blur-sm">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
          className="relative flex items-center"
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Nhập yêu cầu (ví dụ: 'Kiểm tra số dư', 'Gửi 0.05 ETH tới 0x...', 'Xem chính sách Guardrail')..."
            rows={1}
            className="w-full pl-4 pr-12 py-3 rounded-xl bg-background border border-border text-gray-100 placeholder-gray-500 focus:outline-none focus:border-indigo-500 text-xs resize-none"
          />
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="absolute right-2 p-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:hover:bg-indigo-600 text-white transition-all shadow-md shadow-indigo-600/30"
          >
            <Send className="h-4 w-4" />
          </button>
        </form>
        <div className="flex items-center justify-between mt-2 text-[10px] text-gray-500 px-1">
          <span>Nhấn Enter để gửi, Shift + Enter để xuống dòng</span>
          <span className="flex items-center gap-1 text-emerald-400">
            <ShieldCheck className="h-3 w-3" />
            <span>Guardrail & RAG Protected</span>
          </span>
        </div>
      </div>
    </div>
  );
};
