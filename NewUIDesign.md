
<!DOCTYPE html><html class="h-full bg-slate-950 text-slate-100 antialiased" lang="en" style=""><head>
<meta charset="utf-8">
<meta content="width=device-width, initial-scale=1.0" name="viewport">
<title>RebarCraft 3D — NextGen Precast Reinforcement BIM Studio</title>
<!-- Tailwind CSS v3 with Plugins -->
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<!-- Google Fonts: Inter & JetBrains Mono -->
<link href="https://fonts.googleapis.com" rel="preconnect">
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&amp;family=JetBrains+Mono:wght@400;500;600&amp;display=swap" rel="stylesheet">
<!-- Tailwind Configuration -->
<script data-purpose="tailwind-config">
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          fontFamily: {
            sans: ['Inter', 'sans-serif'],
            mono: ['JetBrains Mono', 'monospace'],
          },
          colors: {
            brand: {
              50: '#eff6ff',
              400: '#60a5fa',
              500: '#3b82f6',
              600: '#2563eb',
            },
            cad: {
              dark: '#080C14',
              panel: '#0D131F',
              subpanel: '#131B2B',
              border: '#1E293B',
              hover: '#1E293B',
              t8: '#06b6d4',     /* Cyan */
              t10: '#10b981',    /* Emerald */
              t12: '#84cc16',    /* Lime */
              t16: '#d946ef',    /* Fuchsia / Purple */
              t20: '#f59e0b',    /* Amber */
            }
          }
        }
      }
    }
  </script>
<!-- Custom CAD & Canvas Styles -->
<style data-purpose="cad-layout">
    /* Subtle CAD Grid background */
    .cad-grid-pattern {
      background-size: 32px 32px;
      background-image: 
        linear-gradient(to right, rgba(255, 255, 255, 0.03) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(255, 255, 255, 0.03) 1px, transparent 1px);
    }
    
    /* Custom Scrollbar for High Density Engineering panels */
    ::-webkit-scrollbar {
      width: 5px;
      height: 5px;
    }
    ::-webkit-scrollbar-track {
      background: #090e17;
    }
    ::-webkit-scrollbar-thumb {
      background: #1e293b;
      border-radius: 3px;
    }
    ::-webkit-scrollbar-thumb:hover {
      background: #334155;
    }

    /* 3D Cube Rotation Styling */
    .cube-container {
      perspective: 400px;
    }
    .view-cube {
      width: 44px;
      height: 44px;
      position: relative;
      transform-style: preserve-3d;
      transform: rotateX(-22deg) rotateY(-36deg);
      transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .cube-face {
      position: absolute;
      width: 44px;
      height: 44px;
      border: 1px solid rgba(59, 130, 246, 0.4);
      background: rgba(15, 23, 42, 0.85);
      color: #94a3b8;
      font-size: 9px;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
      text-transform: uppercase;
      user-select: none;
      box-shadow: inset 0 0 8px rgba(59, 130, 246, 0.15);
    }
    .cube-face:hover {
      background: rgba(37, 99, 235, 0.5);
      color: #fff;
    }
    .face-front  { transform: rotateY(  0deg) translateZ(22px); }
    .face-back   { transform: rotateY(180deg) translateZ(22px); }
    .face-right  { transform: rotateY( 90deg) translateZ(22px); }
    .face-left   { transform: rotateY(-90deg) translateZ(22px); }
    .face-top    { transform: rotateX( 90deg) translateZ(22px); }
    .face-bottom { transform: rotateX(-90deg) translateZ(22px); }
  </style>
</head>
<body class="h-full flex flex-col font-sans overflow-hidden select-none bg-slate-950 text-slate-200">
<!-- BEGIN: TopBar -->
<header class="h-14 border-b border-cad-border bg-cad-panel flex items-center justify-between px-3 shrink-0 z-30 shadow-md" data-purpose="app-header">
<!-- Left: Branding & Project Path -->
<div class="flex items-center space-x-3 shrink-0">
<div class="flex items-center space-x-2">
<div class="w-8 h-8 rounded-lg bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-blue-500/20 ring-1 ring-white/10">
<svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
<path d="M21 7.5l-9-5.25L3 7.5m18 0l-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9" stroke-linecap="round" stroke-linejoin="round"></path>
</svg>
</div>
<div>
<div class="flex items-center space-x-1.5 leading-none">
<span class="text-sm font-bold tracking-tight text-white">RebarCraft</span>
<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/30">BIM 4.3</span>
</div>
<div class="flex items-center space-x-1 text-[11px] text-slate-400 font-mono mt-0.5">


<span class="text-blue-400 font-medium">PW-GF-18</span>
</div>
</div>
</div>
<div class="h-5 w-px bg-slate-800 mx-1"></div>
<!-- Quick Status Badge -->
<div class="hidden lg:flex items-center space-x-1.5 px-2 py-1 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs">
<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
<span class="font-mono text-[11px]">BBS Validated</span>
</div>
</div>
<!-- Center: Horizontal Elements Pills Navigation -->
<nav class="flex items-center space-x-1 overflow-x-auto max-w-2xl px-2 py-1 scrollbar-none" data-purpose="element-switcher">
<button class="px-2.5 py-1 text-xs rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 font-mono transition">PC-GF-01</button>
<button class="px-2.5 py-1 text-xs rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 font-mono transition">PW-01-PW</button>
<button class="px-2.5 py-1 text-xs rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 font-mono transition">PW-GF-01</button>
<button class="px-2.5 py-1 text-xs rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 font-mono transition">PW-GF-06</button>
<button class="px-2.5 py-1 text-xs rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 font-mono transition">PW-GF-07</button>
<button class="px-2.5 py-1 text-xs rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 font-mono transition">PW-GF-09</button>
<!-- Active Wall Element -->
<button class="px-3 py-1 text-xs font-semibold rounded-md bg-blue-600 text-white font-mono shadow-sm shadow-blue-500/30 ring-1 ring-blue-400/40 flex items-center space-x-1.5">
<span class="">PW-GF-18</span>
<span class="w-1.5 h-1.5 rounded-full bg-blue-200"></span>
</button>
<button class="px-2.5 py-1 text-xs rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 font-mono transition">PW-GF-25</button>
<button class="px-2.5 py-1 text-xs rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 font-mono transition">PW-GF-26</button>
<button class="px-2.5 py-1 text-xs rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 font-mono transition">PW-GF-45</button>
<button class="px-2.5 py-1 text-xs rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 font-mono transition">SS-GF-01</button>
<button class="p-1 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800" title="Add Element">
<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M12 4v16m8-8H4" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
</button>
</nav>
<!-- Right: View Modes, Export & Actions -->
<div class="flex items-center space-x-2 shrink-0">
<!-- Display mode toggles -->
<div class="hidden sm:flex items-center bg-slate-900 border border-slate-800 rounded-lg p-0.5 text-xs">
<button class="px-2.5 py-1 rounded bg-slate-800 text-blue-400 font-medium flex items-center space-x-1" title="X-Ray Ghosted Rebar View">
<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"></path><circle cx="12" cy="12" r="3"></circle></svg>
<span class="text-[11px]">X-Ray</span>
</button>
<button class="px-2.5 py-1 rounded text-slate-400 hover:text-slate-200 flex items-center space-x-1" title="Solid Shaded View">
<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect height="18" rx="2" width="18" x="3" y="3"></rect></svg>
<span class="text-[11px]">Solid</span>
</button>
<button class="px-2.5 py-1 rounded text-slate-400 hover:text-slate-200 flex items-center space-x-1" title="Pure Wireframe">
<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="m21 16-9 5-9-5V8l9-5 9 5v8Z"></path><path d="M3.27 6.96 12 12.01l8.73-5.05M12 22.08V12"></path></svg>
<span class="text-[11px]">Wire</span>
</button>
</div>
<div class="h-5 w-px bg-slate-800"></div>
<!-- Export Menu Button -->
<div class="relative group">
<button class="flex items-center space-x-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white rounded-lg text-xs font-semibold shadow-md shadow-blue-600/20 transition">
<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
<span class="">Export</span>
<svg class="w-3 h-3 ml-0.5 opacity-80" fill="currentColor" viewBox="0 0 20 20"><path clip-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" fill-rule="evenodd"></path></svg>
</button>
</div>
<!-- App Settings -->
<button class="p-1.5 rounded-lg border border-slate-800 text-slate-400 hover:text-slate-100 hover:bg-slate-800 transition">
<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
</button>
</div>
</header>
<!-- END: TopBar -->
<!-- BEGIN: MainWorkspace -->
<div class="flex-1 flex overflow-hidden relative">
<!-- BEGIN: LeftSidebar -->
<aside class="w-80 xl:w-88 border-r border-cad-border bg-cad-panel flex flex-col shrink-0 z-20" data-purpose="rebar-spec-inspector">
<!-- Element Metric Hero Header -->
<div class="p-3.5 border-b border-cad-border bg-cad-subpanel/60">
<div class="flex items-center justify-between">
<h2 class="text-sm font-semibold tracking-wide text-white font-mono flex items-center space-x-1.5">
<span class="w-2 h-2 rounded bg-blue-500"></span>
<span class="">PW-GF-18</span>
</h2>
<span class="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">Precast Wall</span>
</div>
<div class="text-xs text-slate-400 font-mono mt-1">
          1500 × 5095 × 400 <span class="text-[10px] text-slate-500">mm</span>
</div>
<!-- 3 Quick Metrics Badges -->
<div class="grid grid-cols-3 gap-2 mt-3 pt-2.5 border-t border-slate-800 text-center">
<div class="bg-slate-900/80 p-1.5 rounded border border-slate-800/80">
<div class="text-[10px] text-slate-400 uppercase font-medium">Rebar Count</div>
<div class="text-sm font-bold text-white font-mono">359 <span class="text-[10px] font-normal text-slate-400">bars</span></div>
</div>
<div class="bg-slate-900/80 p-1.5 rounded border border-slate-800/80">
<div class="text-[10px] text-slate-400 uppercase font-medium">Concrete Vol</div>
<div class="text-sm font-bold text-emerald-400 font-mono">3.06 <span class="text-[10px] font-normal text-slate-400">m³</span></div>
</div>
<div class="bg-slate-900/80 p-1.5 rounded border border-slate-800/80">
<div class="text-[10px] text-slate-400 uppercase font-medium">Steel Weight</div>
<div class="text-sm font-bold text-blue-400 font-mono">264 <span class="text-[10px] font-normal text-slate-400">kg</span></div>
</div>
</div>
</div>
<!-- Color Legend Toggle Bar -->
<div class="px-3.5 py-2 border-b border-cad-border bg-slate-900/50 flex items-center justify-between text-xs font-mono">
<span class="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Bar Legend:</span>
<div class="flex items-center space-x-1.5">
<button class="px-1.5 py-0.5 rounded text-[11px] font-semibold bg-cyan-950 text-cyan-400 border border-cyan-800/60 hover:brightness-125" title="Diameter 8mm">T8</button>
<button class="px-1.5 py-0.5 rounded text-[11px] font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800/60 hover:brightness-125" title="Diameter 10mm">T10</button>
<button class="px-1.5 py-0.5 rounded text-[11px] font-semibold bg-lime-950 text-lime-400 border border-lime-800/60 hover:brightness-125" title="Diameter 12mm">T12</button>
<button class="px-1.5 py-0.5 rounded text-[11px] font-semibold bg-fuchsia-950 text-fuchsia-400 border border-fuchsia-800/60 hover:brightness-125" title="Diameter 16mm">T16</button>
<button class="px-1.5 py-0.5 rounded text-[11px] font-semibold bg-amber-950 text-amber-400 border border-amber-800/60 hover:brightness-125" title="Diameter 20mm">T20</button>
</div>
</div>
<!-- Component Layer Tree -->
<div class="px-3.5 py-2.5 border-b border-cad-border" data-purpose="layer-tree">
<div class="flex items-center justify-between mb-2">
<span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Reinforcement Layers</span>
<button class="text-[11px] text-blue-400 hover:underline">Select All</button>
</div>
<div class="space-y-1 text-xs">
<!-- Layer Row: Sleeve -->
<label class="flex items-center justify-between px-2 py-1 rounded hover:bg-slate-800/60 cursor-pointer group transition">
<div class="flex items-center space-x-2">
<input checked="" class="rounded border-slate-700 bg-slate-900 text-blue-600 focus:ring-0 w-3.5 h-3.5" type="checkbox">
<span class="w-2 h-2 rounded-full bg-orange-400"></span>
<span class="text-slate-300 font-medium">sleeve</span>
</div>
<span class="font-mono text-[11px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 group-hover:text-slate-200">6</span>
</label>
<!-- Layer Row: Anchor -->
<label class="flex items-center justify-between px-2 py-1 rounded hover:bg-slate-800/60 cursor-pointer group transition">
<div class="flex items-center space-x-2">
<input checked="" class="rounded border-slate-700 bg-slate-900 text-blue-600 focus:ring-0 w-3.5 h-3.5" type="checkbox">
<span class="w-2 h-2 rounded-full bg-amber-400"></span>
<span class="text-slate-300 font-medium">anchor</span>
</div>
<span class="font-mono text-[11px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 group-hover:text-slate-200">14</span>
</label>
<!-- Layer Row: Face Dowel -->
<label class="flex items-center justify-between px-2 py-1 rounded hover:bg-slate-800/60 cursor-pointer group transition">
<div class="flex items-center space-x-2">
<input checked="" class="rounded border-slate-700 bg-slate-900 text-blue-600 focus:ring-0 w-3.5 h-3.5" type="checkbox">
<span class="w-2 h-2 rounded-full bg-rose-400"></span>
<span class="text-slate-300 font-medium">face-dowel</span>
</div>
<span class="font-mono text-[11px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 group-hover:text-slate-200">6</span>
</label>
<!-- Layer Row: Shape Stirrups -->
<label class="flex items-center justify-between px-2 py-1 rounded hover:bg-slate-800/60 cursor-pointer group transition">
<div class="flex items-center space-x-2">
<input checked="" class="rounded border-slate-700 bg-slate-900 text-blue-600 focus:ring-0 w-3.5 h-3.5" type="checkbox">
<span class="w-2 h-2 rounded-full bg-cyan-400"></span>
<span class="text-slate-300 font-medium">shape (stirrups)</span>
</div>
<span class="font-mono text-[11px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 group-hover:text-slate-200">138</span>
</label>
<!-- Layer Row: Diagonal -->
<label class="flex items-center justify-between px-2 py-1 rounded hover:bg-slate-800/60 cursor-pointer group transition">
<div class="flex items-center space-x-2">
<input checked="" class="rounded border-slate-700 bg-slate-900 text-blue-600 focus:ring-0 w-3.5 h-3.5" type="checkbox">
<span class="w-2 h-2 rounded-full bg-lime-400"></span>
<span class="text-slate-300 font-medium">diagonal ties</span>
</div>
<span class="font-mono text-[11px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 group-hover:text-slate-200">2</span>
</label>
<!-- Layer Row: Vertical Mesh -->
<label class="flex items-center justify-between px-2 py-1 rounded hover:bg-slate-800/60 cursor-pointer group transition">
<div class="flex items-center space-x-2">
<input checked="" class="rounded border-slate-700 bg-slate-900 text-blue-600 focus:ring-0 w-3.5 h-3.5" type="checkbox">
<span class="w-2 h-2 rounded-full bg-fuchsia-400"></span>
<span class="text-slate-300 font-medium">v-mesh distribution</span>
</div>
<span class="font-mono text-[11px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 group-hover:text-slate-200">87</span>
</label>
<!-- Layer Row: Horizontal Mesh -->
<label class="flex items-center justify-between px-2 py-1 rounded hover:bg-slate-800/60 cursor-pointer group transition">
<div class="flex items-center space-x-2">
<input checked="" class="rounded border-slate-700 bg-slate-900 text-blue-600 focus:ring-0 w-3.5 h-3.5" type="checkbox">
<span class="w-2 h-2 rounded-full bg-indigo-400"></span>
<span class="text-slate-300 font-medium">h-mesh distribution</span>
</div>
<span class="font-mono text-[11px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 group-hover:text-slate-200">126</span>
</label>
</div>
</div>
<!-- Rebar Layer Placement Specifications (Scrollable feed) -->
<div class="flex-1 flex flex-col min-h-0 bg-slate-950/40">
<div class="p-3 border-b border-cad-border flex items-center justify-between">
<span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Layer Specifications</span>
<span class="text-[10px] text-slate-500 font-mono">14 groups</span>
</div>
<div class="flex-1 overflow-y-auto p-2 space-y-1.5 text-xs font-mono" data-purpose="rebar-specification-feed">
<!-- Spec Item 1 -->
<div class="p-2 rounded bg-slate-900/90 border border-slate-800/90 hover:border-blue-500/60 hover:bg-slate-900 transition group cursor-pointer">
<div class="flex items-center justify-between">
<div class="flex items-center space-x-1.5">
<span class="w-2 h-2 rounded-full bg-cyan-400"></span>
<span class="text-white font-semibold">Horizontal T8</span>
<span class="text-cyan-400 font-bold">@ 40 mm</span>
</div>
<span class="text-slate-400 text-[11px]">31 bars</span>
</div>
<div class="flex items-center justify-between text-[11px] text-slate-400 mt-1">
<span class="">L: 1.07 – 1.46 m</span>
<span class="text-slate-500">z = 233.9</span>
</div>
</div>
<!-- Spec Item 2 -->
<div class="p-2 rounded bg-slate-900/90 border border-slate-800/90 hover:border-blue-500/60 hover:bg-slate-900 transition group cursor-pointer">
<div class="flex items-center justify-between">
<div class="flex items-center space-x-1.5">
<span class="w-2 h-2 rounded-full bg-cyan-400"></span>
<span class="text-white font-semibold">Horizontal T8</span>
<span class="text-cyan-400 font-bold">@ 25 mm</span>
</div>
<span class="text-slate-400 text-[11px]">107 bars</span>
</div>
<div class="flex items-center justify-between text-[11px] text-slate-400 mt-1">
<span class="">L: 0.14 – 1.44 m</span>
<span class="text-slate-500">z = 366.0</span>
</div>
</div>
<!-- Spec Item 3 -->
<div class="p-2 rounded bg-slate-900/90 border border-slate-800/90 hover:border-blue-500/60 hover:bg-slate-900 transition group cursor-pointer">
<div class="flex items-center justify-between">
<div class="flex items-center space-x-1.5">
<span class="w-2 h-2 rounded-full bg-lime-400"></span>
<span class="text-white font-semibold">Horizontal T12</span>
<span class="text-lime-400 font-bold">@ 165 mm</span>
</div>
<span class="text-slate-400 text-[11px]">9 bars</span>
</div>
<div class="flex items-center justify-between text-[11px] text-slate-400 mt-1">
<span class="">L: 1.04 – 1.11 m</span>
<span class="text-slate-500">z = 49.4</span>
</div>
</div>
<!-- Spec Item 4 -->
<div class="p-2 rounded bg-slate-900/90 border border-slate-800/90 hover:border-blue-500/60 hover:bg-slate-900 transition group cursor-pointer">
<div class="flex items-center justify-between">
<div class="flex items-center space-x-1.5">
<span class="w-2 h-2 rounded-full bg-cyan-400"></span>
<span class="text-white font-semibold">Vertical T8</span>
<span class="text-cyan-400 font-bold">@ 40 mm</span>
</div>
<span class="text-slate-400 text-[11px]">25 bars</span>
</div>
<div class="flex items-center justify-between text-[11px] text-slate-400 mt-1">
<span class="">L: 0.30 – 5.03 m</span>
<span class="text-slate-500">z = 242.0</span>
</div>
</div>
<!-- Spec Item 5 -->
<div class="p-2 rounded bg-slate-900/90 border border-slate-800/90 hover:border-blue-500/60 hover:bg-slate-900 transition group cursor-pointer">
<div class="flex items-center justify-between">
<div class="flex items-center space-x-1.5">
<span class="w-2 h-2 rounded-full bg-cyan-400"></span>
<span class="text-white font-semibold">Vertical T8</span>
<span class="text-cyan-400 font-bold">@ 90 mm</span>
</div>
<span class="text-slate-400 text-[11px]">30 bars</span>
</div>
<div class="flex items-center justify-between text-[11px] text-slate-400 mt-1">
<span class="">L: 0.30 – 5.03 m</span>
<span class="text-slate-500">z = 358.0</span>
</div>
</div>
<!-- Spec Item 6 -->
<div class="p-2 rounded bg-slate-900/90 border border-slate-800/90 hover:border-blue-500/60 hover:bg-slate-900 transition group cursor-pointer">
<div class="flex items-center justify-between">
<div class="flex items-center space-x-1.5">
<span class="w-2 h-2 rounded-full bg-fuchsia-400"></span>
<span class="text-white font-semibold">Vertical T16</span>
<span class="text-fuchsia-400 font-bold">@ 25 mm</span>
</div>
<span class="text-slate-400 text-[11px]">5 bars</span>
</div>
<div class="flex items-center justify-between text-[11px] text-slate-400 mt-1">
<span class="">L: 1.74 m</span>
<span class="text-slate-500">z = 56.0</span>
</div>
</div>
<!-- Spec Item 7 -->
<div class="p-2 rounded bg-slate-900/90 border border-slate-800/90 hover:border-blue-500/60 hover:bg-slate-900 transition group cursor-pointer">
<div class="flex items-center justify-between">
<div class="flex items-center space-x-1.5">
<span class="w-2 h-2 rounded-full bg-fuchsia-400"></span>
<span class="text-white font-semibold">Vertical T16</span>
<span class="text-fuchsia-400 font-bold">@ 120 mm</span>
</div>
<span class="text-slate-400 text-[11px]">2 bars</span>
</div>
<div class="flex items-center justify-between text-[11px] text-slate-400 mt-1">
<span class="">L: 1.74 m</span>
<span class="text-slate-500">z = 136.3</span>
</div>
</div>
<!-- Spec Item 8 -->
<div class="p-2 rounded bg-slate-900/90 border border-slate-800/90 hover:border-blue-500/60 hover:bg-slate-900 transition group cursor-pointer">
<div class="flex items-center justify-between">
<div class="flex items-center space-x-1.5">
<span class="w-2 h-2 rounded-full bg-amber-400"></span>
<span class="text-white font-semibold">Vertical T20</span>
<span class="text-amber-400 font-bold">@ 450 mm</span>
</div>
<span class="text-slate-400 text-[11px]">6 bars</span>
</div>
<div class="flex items-center justify-between text-[11px] text-slate-400 mt-1">
<span class="">L: 2.02 – 4.64 m</span>
<span class="text-slate-500">z = 300.0</span>
</div>
</div>
</div>
</div>
</aside>
<!-- END: LeftSidebar -->
<!-- BEGIN: CenterViewport -->
<main class="flex-1 flex flex-col relative bg-cad-dark overflow-hidden" data-purpose="3d-cad-viewport">
<!-- Interactive 3D Canvas Container -->
<div class="flex-1 relative cad-grid-pattern flex items-center justify-center overflow-hidden">
<!-- High-fidelity Scalable Vector 3D Precast Column with Internal Rebar Reinforcement -->

<!-- Viewport Floating Navigation View Cube (Autodesk / Revit style) -->
<div class="absolute top-4 right-4 z-20 flex flex-col items-center">
<div class="cube-container p-2 rounded-xl bg-slate-900/80 border border-slate-800 shadow-xl backdrop-blur">
<div class="view-cube">
<div class="cube-face face-front">Front</div>
<div class="cube-face face-back">Back</div>
<div class="cube-face face-right">Right</div>
<div class="cube-face face-left">Left</div>
<div class="cube-face face-top">Top</div>
<div class="cube-face face-bottom">Iso</div>
</div>
<div class="flex items-center justify-between text-[9px] font-mono text-slate-400 mt-2 px-1">


</div>
</div>
</div>
<!-- Viewport Floating CAD Controls Dock (Bottom Center) -->
<div class="absolute bottom-5 left-1/2 -translate-x-1/2 z-20 flex items-center bg-slate-900/90 border border-slate-800 backdrop-blur-md rounded-xl p-1.5 shadow-2xl space-x-1">
<button class="p-2 rounded-lg bg-blue-600/20 text-blue-400 hover:bg-blue-600 hover:text-white transition" title="Orbit (RMB + Drag)">
<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
</button>
<button class="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition" title="Pan (MMB + Drag)">
<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M7 11.5V14m0-2.5v-6a1.5 1.5 0 113 0m-3 6a1.5 1.5 0 00-3 0v2a7.5 7.5 0 0015 0v-5a1.5 1.5 0 00-3 0m-6-3V11m0-5.5v-1a1.5 1.5 0 013 0v1m0 0V11m0-5.5a1.5 1.5 0 013 0v3m0 0V11" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
</button>
<button class="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition" title="Zoom Extents (Z)">
<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v6m3-3H7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
</button>
<div class="h-5 w-px bg-slate-800"></div>
<button class="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition" title="Cross Section Plane Cut">
<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879M12 12L9.121 9.121m0 5.758a3 3 0 10-4.243 4.243 3 3 0 004.243-4.243zm0-5.758a3 3 0 10-4.243-4.243 3 3 0 004.243 4.243z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
</button>
<button class="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition" title="Measure Distances (M)">
<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M6 18L18 6M6 6l12 12" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
</button>
<button class="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition" title="Toggle Dimension Lines">
<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M7 20l4-16m2 16l4-16M6 9h14M4 15h14" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
</button>
</div>
<!-- 3D Coordinate Axis Gizmo (Bottom Left) -->
<div class="absolute bottom-4 left-4 z-20 flex items-center space-x-2 bg-slate-900/60 p-2 rounded-lg border border-slate-800/80 backdrop-blur">
<div class="relative w-8 h-8 font-mono font-bold text-[9px]">
<span class="absolute right-0 top-1 text-red-500">X</span>
<span class="absolute left-1 top-0 text-emerald-500">Y</span>
<span class="absolute right-2 bottom-0 text-blue-500">Z</span>
<svg class="w-full h-full" viewBox="0 0 32 32">
<line stroke="#ef4444" stroke-width="2" x1="16" x2="28" y1="16" y2="16"></line>
<line stroke="#10b981" stroke-width="2" x1="16" x2="16" y1="16" y2="4"></line>
<line stroke="#3b82f6" stroke-width="2" x1="16" x2="6" y1="16" y2="26"></line>
</svg>
</div>
<span class="text-[11px] font-mono text-slate-400">UCS: Global</span>
</div>
<!-- Clash Detection Floating Info Toast -->
<div class="absolute top-4 left-4 z-20 flex items-center space-x-2 bg-slate-900/90 border border-slate-800 px-3 py-1.5 rounded-lg shadow-lg text-xs backdrop-blur">
<span class="w-2 h-2 rounded-full bg-emerald-400"></span>
<span class="text-slate-300 font-medium">BIM Clash Check:</span>
<span class="text-emerald-400 font-mono font-semibold">0 Collisions detected</span>
</div>
</div>
</main>
<!-- END: CenterViewport -->
<!-- BEGIN: RightSidebar -->
<aside class="w-80 xl:w-96 border-l border-cad-border bg-cad-panel flex flex-col shrink-0 z-20 overflow-y-auto" data-purpose="geometry-and-bbs-panel">
<!-- Panel Section 1: Parametric Concrete Geometry Form -->
<section class="p-4 border-b border-cad-border" data-purpose="geometry-parameters">
<div class="flex items-center justify-between mb-3">
<h3 class="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center space-x-1.5">
<svg class="w-3.5 h-3.5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
<span class="">Parametric Dimensions</span>
</h3>
<button class="text-[11px] text-slate-400 hover:text-slate-200 font-mono transition" title="Reset to defaults">Reset</button>
</div>
<!-- Inputs Grid -->
<div class="space-y-2.5">
<div class="grid grid-cols-3 gap-2">
<!-- Width -->
<div>
<label class="block text-[10px] uppercase font-mono text-slate-400 mb-1">Width (X)</label>
<div class="relative">
<input class="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs font-mono text-white focus:ring-1 focus:ring-blue-500 focus:border-blue-500" type="number" value="1500">
<span class="absolute right-1.5 top-1 text-[10px] font-mono text-slate-500">mm</span>
</div>
</div>
<!-- Height -->
<div>
<label class="block text-[10px] uppercase font-mono text-slate-400 mb-1">Height (Z)</label>
<div class="relative">
<input class="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs font-mono text-white focus:ring-1 focus:ring-blue-500 focus:border-blue-500" type="number" value="5095">
<span class="absolute right-1.5 top-1 text-[10px] font-mono text-slate-500">mm</span>
</div>
</div>
<!-- Thickness -->
<div>
<label class="block text-[10px] uppercase font-mono text-slate-400 mb-1">Thick (Y)</label>
<div class="relative">
<input class="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs font-mono text-white focus:ring-1 focus:ring-blue-500 focus:border-blue-500" type="number" value="400">
<span class="absolute right-1.5 top-1 text-[10px] font-mono text-slate-500">mm</span>
</div>
</div>
</div>
<!-- Apply Button -->
<div class="flex items-center space-x-2 pt-1">
<button class="flex-1 bg-blue-600 hover:bg-blue-500 text-white rounded font-medium text-xs py-1.5 shadow transition">
              Apply Changes
            </button>
<button class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded font-medium text-xs transition">
              Clear
            </button>
</div>
</div>
</section>
<!-- Panel Section 2: Quick Action Deliverables -->
<section class="p-3 border-b border-cad-border bg-slate-900/30" data-purpose="export-actions">
<div class="text-[10px] uppercase font-mono font-semibold text-slate-400 mb-2">Export Deliverables</div>
<div class="grid grid-cols-3 gap-1.5">
<button class="flex flex-col items-center justify-center p-2 rounded-lg bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 hover:border-blue-500/50 transition group">
<svg class="w-4 h-4 text-slate-400 group-hover:text-blue-400 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
<span class="text-[11px] font-mono font-semibold text-slate-300">DXF 2D</span>
</button>
<button class="flex flex-col items-center justify-center p-2 rounded-lg bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 hover:border-emerald-500/50 transition group">
<svg class="w-4 h-4 text-slate-400 group-hover:text-emerald-400 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
<span class="text-[11px] font-mono font-semibold text-slate-300">Report</span>
</button>
<button class="flex flex-col items-center justify-center p-2 rounded-lg bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 hover:border-rose-500/50 transition group">
<svg class="w-4 h-4 text-slate-400 group-hover:text-rose-400 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg>
<span class="text-[11px] font-mono font-semibold text-slate-300">BBS PDF</span>
</button>
</div>
</section>
<!-- Panel Section 3: Bar Bending Schedule (BBS Table) -->
<section class="p-3.5 flex-1 flex flex-col min-h-0" data-purpose="bar-bending-schedule">
<div class="flex items-center justify-between mb-2">
<div>
<h3 class="text-xs font-bold uppercase tracking-wider text-slate-200">Bar Schedule (BBS)</h3>
<p class="text-[10px] text-slate-400 font-mono">BBS exported: original geometry</p>
</div>
<span class="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">BS 8666:2020</span>
</div>
<!-- High-density Data Table -->
<div class="border border-cad-border rounded-lg overflow-hidden bg-slate-900/60 shadow-sm">
<table class="w-full text-left font-mono text-xs">
<thead class="bg-slate-800/80 text-[10px] text-slate-400 uppercase border-b border-cad-border">
<tr>
<th class="py-1.5 px-2.5">Bar</th>
<th class="py-1.5 px-2 text-right">Count</th>
<th class="py-1.5 px-2 text-right">Len (m)</th>
<th class="py-1.5 px-2 text-right">kg/m</th>
<th class="py-1.5 px-2.5 text-right">Mass (kg)</th>
</tr>
</thead>
<tbody class="divide-y divide-slate-800/80 text-slate-300">
<!-- Row: T8 -->
<tr class="hover:bg-slate-800/40 transition">
<td class="py-1.5 px-2.5 font-semibold text-cyan-400 flex items-center space-x-1.5">
<span class="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>
<span class="">T8</span>
</td>
<td class="py-1.5 px-2 text-right">305</td>
<td class="py-1.5 px-2 text-right">306.9</td>
<td class="py-1.5 px-2 text-right text-slate-400">0.395</td>
<td class="py-1.5 px-2.5 text-right font-medium text-white">121.25</td>
</tr>
<!-- Row: T10 -->
<tr class="hover:bg-slate-800/40 transition">
<td class="py-1.5 px-2.5 font-semibold text-emerald-400 flex items-center space-x-1.5">
<span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
<span class="">T10</span>
</td>
<td class="py-1.5 px-2 text-right">7</td>
<td class="py-1.5 px-2 text-right">15.8</td>
<td class="py-1.5 px-2 text-right text-slate-400">0.617</td>
<td class="py-1.5 px-2.5 text-right font-medium text-white">9.72</td>
</tr>
<!-- Row: T12 -->
<tr class="hover:bg-slate-800/40 transition">
<td class="py-1.5 px-2.5 font-semibold text-lime-400 flex items-center space-x-1.5">
<span class="w-1.5 h-1.5 rounded-full bg-lime-400"></span>
<span class="">T12</span>
</td>
<td class="py-1.5 px-2 text-right">4</td>
<td class="py-1.5 px-2 text-right">4.4</td>
<td class="py-1.5 px-2 text-right text-slate-400">0.889</td>
<td class="py-1.5 px-2.5 text-right font-medium text-white">3.88</td>
</tr>
<!-- Row: T16 -->
<tr class="hover:bg-slate-800/40 transition">
<td class="py-1.5 px-2.5 font-semibold text-fuchsia-400 flex items-center space-x-1.5">
<span class="w-1.5 h-1.5 rounded-full bg-fuchsia-400"></span>
<span class="">T16</span>
</td>
<td class="py-1.5 px-2 text-right">39</td>
<td class="py-1.5 px-2 text-right">66.0</td>
<td class="py-1.5 px-2 text-right text-slate-400">1.580</td>
<td class="py-1.5 px-2.5 text-right font-medium text-white">104.25</td>
</tr>
<!-- Row: T20 -->
<tr class="hover:bg-slate-800/40 transition">
<td class="py-1.5 px-2.5 font-semibold text-amber-400 flex items-center space-x-1.5">
<span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
<span class="">T20</span>
</td>
<td class="py-1.5 px-2 text-right">4</td>
<td class="py-1.5 px-2 text-right">10.1</td>
<td class="py-1.5 px-2 text-right text-slate-400">2.469</td>
<td class="py-1.5 px-2.5 text-right font-medium text-white">24.92</td>
</tr>
</tbody>
<!-- Total BBS Row -->
<tfoot class="bg-slate-800/90 font-semibold border-t-2 border-slate-700 text-white">
<tr>
<td class="py-2 px-2.5">Total</td>
<td class="py-2 px-2 text-right text-blue-400">359</td>
<td class="py-2 px-2 text-right">403.1</td>
<td class="py-2 px-2 text-right text-slate-400">—</td>
<td class="py-2 px-2.5 text-right text-emerald-400 font-bold">264.02</td>
</tr>
</tfoot>
</table>
</div>
<!-- Formula and Volume Metadata Footer -->
<div class="mt-3 p-2.5 rounded-lg bg-cad-subpanel border border-cad-border space-y-1 text-[11px] font-mono">
<div class="flex items-center justify-between text-slate-300">
<span class="">Concrete Volume:</span>
<span class="text-white font-semibold">3.06 m³</span>
</div>
<div class="flex items-center justify-between text-slate-300">
<span class="">Structural Mass:</span>
<span class="text-white font-semibold">7,643 kg</span>
</div>
<div class="flex items-center justify-between text-slate-400 pt-1 border-t border-slate-800/80">
<span class="">Unit weight calc:</span>
<span class="text-blue-400 font-bold">d² / 162 kg/m</span>
</div>
</div>
<!-- Rebar Diameter Mass Distribution Bar -->
<div class="mt-3">
<div class="flex items-center justify-between text-[10px] font-mono text-slate-400 mb-1">
<span class="">Weight Distribution</span>
<span class="">264.02 kg total</span>
</div>
<div class="h-2 w-full bg-slate-800 rounded-full overflow-hidden flex">
<!-- T8: 121.25kg (~46%) -->
<div class="h-full bg-cyan-400" style="width: 46%" title="T8: 121.25 kg (46%)"></div>
<!-- T10: 9.72kg (~4%) -->
<div class="h-full bg-emerald-400" style="width: 4%" title="T10: 9.72 kg (4%)"></div>
<!-- T12: 3.88kg (~1.5%) -->
<div class="h-full bg-lime-400" style="width: 2%" title="T12: 3.88 kg (1.5%)"></div>
<!-- T16: 104.25kg (~39.5%) -->
<div class="h-full bg-fuchsia-400" style="width: 39.5%" title="T16: 104.25 kg (39.5%)"></div>
<!-- T20: 24.92kg (~9%) -->
<div class="h-full bg-amber-400" style="width: 9.5%" title="T20: 24.92 kg (9%)"></div>
</div>
<div class="flex justify-between items-center text-[9px] font-mono text-slate-500 mt-1">
<span class="">T8 (46%)</span>
<span class="">T16 (39%)</span>
<span class="">T20 (9%)</span>
</div>
</div>
</section>
</aside>
<!-- END: RightSidebar -->
</div>
<!-- END: MainWorkspace -->
<!-- BEGIN: BottomStatusBar -->
<footer class="h-7 border-t border-cad-border bg-cad-panel flex items-center justify-between px-3 text-[11px] font-mono text-slate-400 shrink-0 z-30" data-purpose="app-status-bar">
<div class="flex items-center space-x-3">
<div class="flex items-center space-x-1 text-slate-300">
<span class="w-1.5 h-1.5 rounded-full bg-blue-500"></span>
<span class="">Ready</span>
</div>
<span class="">|</span>
<span class="">Cursor: X: 450.2 mm, Y: 120.0 mm, Z: 233.9 mm</span>
<span class="hidden md:inline">|</span>
<span class="hidden md:inline">Renderer: WebGL 2.0 (High Precision 60 FPS)</span>
</div>
<div class="flex items-center space-x-3">
<span class="text-blue-400">Unit: Millimeters (mm)</span>
<span class="">|</span>
<span class="hover:text-slate-200 cursor-pointer">Drafting Grid: 10 mm</span>
<span class="">|</span>
<span class="text-slate-500">v2.4.0-bim</span>
</div>
</footer>
<!-- END: BottomStatusBar -->


</body></html>

