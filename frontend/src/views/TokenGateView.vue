<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const token = ref("");
const loading = ref(false);
const error = ref(false);
const errorMsg = ref("");

async function submit(): Promise<void> {
  if (!token.value.trim()) return;
  loading.value = true;
  error.value = false;
  try {
    await auth.verify(token.value.trim());
    const redirect = (route.query.redirect as string) || "/";
    await router.push(redirect);
  } catch (e) {
    error.value = true;
    errorMsg.value = e instanceof Error ? e.message : "令牌不正确";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="gate">
    <n-card class="gate-card" :bordered="true">
      <div class="gate-title">ComfyUI LaunchPad</div>
      <div class="gate-sub">输入访问令牌以继续</div>
      <n-input
        v-model:value="token"
        type="password"
        show-password-on="click"
        placeholder="访问令牌"
        :class="{ shake: error }"
        :disabled="loading"
        @keyup.enter="submit"
      />
      <n-button
        type="primary"
        block
        style="margin-top: 16px"
        :loading="loading"
        :disabled="!token.trim()"
        @click="submit"
      >
        进入面板
      </n-button>
      <n-alert v-if="error" type="error" style="margin-top: 12px" :show-icon="false">
        {{ errorMsg }}
      </n-alert>
      <div class="gate-hint">
        令牌由安装脚本生成（安装完成后打印一次）；可在实例内执行
        <code class="mono">launchpad_cli.py token-reset</code> 重新生成
      </div>
    </n-card>
  </div>
</template>

<style scoped>
.gate {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--lp-bg);
}

.gate-card {
  width: 380px;
  border-radius: 12px;
}

.gate-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--lp-primary);
  text-align: center;
}

.gate-sub {
  text-align: center;
  color: var(--lp-text-2);
  margin: 8px 0 20px;
}

.gate-hint {
  margin-top: 16px;
  font-size: 12px;
  color: var(--lp-text-2);
  line-height: 1.6;
}

.shake {
  animation: shake 0.3s;
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-6px); }
  75% { transform: translateX(6px); }
}
</style>
