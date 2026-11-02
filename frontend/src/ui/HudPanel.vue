<script setup lang="ts">
/**
 * HUD 面板：外框以 clip-path 切角（依主題可換圓角或括角），
 * 外層包一層 drop-shadow 產生發光描邊（clip-path 會裁掉 box-shadow）。
 */
withDefaults(
  defineProps<{
    title?: string;
    /** 右上角的等寬識別碼，例如 SEC-02。 */
    code?: string;
    eyebrow?: string;
    tone?: "default" | "accent" | "warn" | "danger";
    as?: string;
    headingLevel?: 2 | 3;
  }>(),
  { title: "", code: "", eyebrow: "", tone: "default", as: "section", headingLevel: 2 },
);
</script>

<template>
  <component :is="as" class="hud" :class="`hud--${tone}`">
    <div class="hud__frame">
      <div class="hud__body">
        <header v-if="title || $slots.actions || $slots.meta || eyebrow" class="hud__head">
          <div class="hud__titles">
            <p v-if="eyebrow" class="hud__eyebrow">{{ eyebrow }}</p>
            <component :is="`h${headingLevel}`" v-if="title" class="hud__title">
              {{ title }}
              <slot name="meta" />
            </component>
          </div>
          <div class="hud__actions">
            <slot name="actions" />
            <span v-if="code" class="hud__code num" aria-hidden="true">{{ code }}</span>
          </div>
        </header>
        <slot />
      </div>
    </div>
  </component>
</template>

<style scoped>
.hud {
  display: block;
  filter: drop-shadow(0 0 var(--glow-size) var(--glow));
  min-width: 0;
}
.hud__frame {
  clip-path: var(--panel-clip);
  border-radius: var(--panel-radius);
  padding: 1px;
  background: linear-gradient(135deg, var(--accent) 0%, var(--line-strong) 22%, var(--line) 60%, var(--accent-2) 100%);
}
.hud--warn .hud__frame {
  background: linear-gradient(135deg, var(--warn), var(--line) 50%, var(--warn));
}
.hud--danger .hud__frame {
  background: linear-gradient(135deg, var(--danger), var(--line) 50%, var(--danger));
}
.hud--accent .hud__frame {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
}
.hud__body {
  position: relative;
  clip-path: var(--panel-clip);
  border-radius: calc(var(--panel-radius) - 1px);
  background:
    linear-gradient(180deg, var(--surface-sheen), transparent 40%),
    var(--surface);
  padding: var(--pad);
  height: 100%;
  box-sizing: border-box;
}
/* 括角主題：四角的 L 形框線 */
.hud__body::before,
.hud__body::after {
  content: "";
  position: absolute;
  width: 14px;
  height: 14px;
  opacity: var(--bracket);
  pointer-events: none;
}
.hud__body::before {
  top: 4px;
  left: 4px;
  border-top: 2px solid var(--accent);
  border-left: 2px solid var(--accent);
}
.hud__body::after {
  right: 4px;
  bottom: 4px;
  border-right: 2px solid var(--accent-2);
  border-bottom: 2px solid var(--accent-2);
}
.hud__head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--gap);
  margin-bottom: var(--gap);
  padding-bottom: calc(var(--gap) * 0.6);
  border-bottom: 1px dashed var(--line);
}
.hud__titles {
  min-width: 0;
}
.hud__eyebrow {
  margin: 0 0 2px;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--accent);
}
.hud__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.hud__actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}
.hud__code {
  font-size: 0.68rem;
  color: var(--ink-faint);
  letter-spacing: 0.12em;
}
</style>
