<script lang="ts">
import type { MarketItem } from '@/api/core'
import { Button, FileUpload, Listbox, ToggleSwitch } from 'primevue'
import { ref } from 'vue'
import AgentAPI from '@/api/agent'
import API from '@/api/core'
import BoxContainer from '@/components/BoxContainer.vue'

interface Skill extends MarketItem {
  installFailed?: boolean
}

const SKILLS = ref<(Skill)[]>([])
</script>

<script setup lang="ts">
API.getMarketItems().then((res) => {
  SKILLS.value = res.items
})

function installSkill(skillId: Skill['id']) {
  const skill = SKILLS.value.find(skill => skill.id === skillId)!
  API.installMarketItem(skillId).then(() => {
    if (skill) {
      skill.installed = true
    }
  }).catch(() => {
    skill.installFailed = true
  })
}

function updateSkillEnabled(skill: Skill) {
  AgentAPI.setSkillEnabled(skill.id, skill.enabled).then((res) => {
    console.log(res)
  })
}
</script>

<template>
  <BoxContainer>
    <div class="h-full flex flex-col gap-4">
      <div class="flex items-center justify-between">
        <div class="font-bold text-xl">技能工坊</div>
        <FileUpload mode="basic" multiple auto choose-label="上传 Skill" />
      </div>
      <div class="overflow-hidden h-full">
        <Listbox
          class="h-full flex! flex-col" scroll-height="100%"
          :options="SKILLS" filter :filter-fields="['id', 'title', 'description']"
          empty-message="Loading skills..."
        >
          <template #option="{ option }: { option: Skill }">
            <div class="w-full flex items-center justify-between">
              <div class="flex flex-col">
                <div>{{ option.title }}</div>
                <div class="text-sm text-gray-500">{{ option.description }}</div>
              </div>
              <ToggleSwitch v-if="option.installed" v-model="option.enabled" @change="updateSkillEnabled(option)" />
              <Button v-else :severity="option.installFailed ? 'danger' : 'success'" @click="installSkill(option.id)">
                {{ option.installFailed ? '安装失败' : '安装' }}
              </Button>
            </div>
          </template>
        </Listbox>
      </div>
    </div>
  </BoxContainer>
</template>
