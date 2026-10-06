import type { Metadata } from "next";
import "./globals.css";
import { WalletProvider } from "@/context/WalletContext";

export const metadata: Metadata = {
  title: "Web3 AI Agent | Autonomous Blockchain & Smart Contract Executor",
  description: "AI-powered conversational interface for EVM blockchains and smart contract interaction.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" className="dark">
      <body className="min-h-screen bg-background text-gray-100 antialiased selection:bg-indigo-500 selection:text-white">
        <WalletProvider>{children}</WalletProvider>
      </body>
    </html>
  );
}

