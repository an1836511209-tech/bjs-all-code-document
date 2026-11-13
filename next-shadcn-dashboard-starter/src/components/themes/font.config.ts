// ============================================================
// Font Configuration
// ============================================================
// Geist is loaded from the local `geist` npm package (font files
// ship in node_modules) — zero network dependency at dev/build
// time, so it works without access to Google Fonts.
// All other faces fall back to the system font stack
// (PingFang SC / Microsoft YaHei for Chinese text).
// ============================================================

import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';

import { cn } from '@/lib/utils';

export const fontVariables = cn(GeistSans.variable, GeistMono.variable);
