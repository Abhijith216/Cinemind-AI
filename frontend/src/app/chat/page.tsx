"use client";

import { motion } from "framer-motion";
import { MessagesSquare } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function ChatPage() {
  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-16">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <h1 className="text-3xl font-bold tracking-tight">Chat</h1>
        <p className="mt-2 text-muted-foreground">
          Multi-turn discovery: describe a mood, answer clarifying questions,
          refine — and get explained picks.
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.15 }}
        className="mt-8"
      >
        <Card className="border-dashed bg-card/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <MessagesSquare className="h-5 w-5 text-primary" />
              Conversation shell lands here
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p>
              This page will wire the chat transcript to{" "}
              <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                POST /api/chat/message
              </code>
              : the assistant&rsquo;s clarifying questions, ranked movie cards
              with per-movie explanations, and the matched-attribute graph data
              for each result.
            </p>
            <p>
              The typed client methods already exist:{" "}
              <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                api.chat.sendMessage()
              </code>{" "}
              and{" "}
              <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                api.chat.getSession()
              </code>
              .
            </p>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}
