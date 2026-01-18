import { create } from 'zustand';
import { tagsApi } from '../api';
import type { TagValue, WSTagUpdatePayload } from '../types';

interface TagsState {
  tags: Map<string, TagValue>;
  tagList: TagValue[];
  isLoading: boolean;
  error: string | null;
  lastUpdate: number | null;

  // Actions
  fetchTags: () => Promise<void>;
  writeTag: (name: string, value: number | string | boolean) => Promise<boolean>;
  updateTag: (payload: WSTagUpdatePayload) => void;
  getTag: (name: string) => TagValue | undefined;
}

export const useTagsStore = create<TagsState>((set, get) => ({
  tags: new Map(),
  tagList: [],
  isLoading: false,
  error: null,
  lastUpdate: null,

  fetchTags: async () => {
    set({ isLoading: true, error: null });

    try {
      const response = await tagsApi.list();

      const tags = new Map<string, TagValue>();
      for (const tag of response.tags) {
        tags.set(tag.name, tag);
      }

      set({
        tags,
        tagList: response.tags,
        isLoading: false,
        lastUpdate: Date.now(),
      });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch tags',
        isLoading: false,
      });
    }
  },

  writeTag: async (name, value) => {
    try {
      const updatedTag = await tagsApi.write(name, { value });

      // Update local state
      const tags = new Map(get().tags);
      tags.set(name, updatedTag);

      const tagList = get().tagList.map((tag) =>
        tag.name === name ? updatedTag : tag
      );

      set({ tags, tagList, lastUpdate: Date.now() });
      return true;
    } catch {
      return false;
    }
  },

  updateTag: (payload) => {
    const { tag_name, value, quality, timestamp } = payload;

    const existingTag = get().tags.get(tag_name);
    const updatedTag: TagValue = {
      name: tag_name,
      value,
      quality,
      timestamp,
      unit: existingTag?.unit,
      description: existingTag?.description,
    };

    const tags = new Map(get().tags);
    tags.set(tag_name, updatedTag);

    const tagList = get().tagList.map((tag) =>
      tag.name === tag_name ? updatedTag : tag
    );

    // If tag doesn't exist in list, add it
    if (!existingTag) {
      tagList.push(updatedTag);
    }

    set({ tags, tagList, lastUpdate: Date.now() });
  },

  getTag: (name) => {
    return get().tags.get(name);
  },
}));
