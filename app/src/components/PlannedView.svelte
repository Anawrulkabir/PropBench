<script lang="ts">
  // A screen whose science is not built yet: the layout of the mockup is shown, actions are disabled.
  interface Props {
    title: string;
    milestone: string;
    description: string;
    mockup?: string;
  }
  let { title, milestone, description, mockup = "" }: Props = $props();
</script>

<div class="planned">
  <div class="notice row"><b>{title}</b><span class="spacer"></span><span>planned: {milestone}</span></div>
  <p>{description}</p>
  {#if mockup}<p class="muted">Design: design/mockups/{mockup}</p>{/if}
</div>

<style>
  .planned {
    display: grid;
    gap: 8px;
    align-content: start;
  }
  p {
    margin: 0;
    line-height: 1.5;
  }
</style>
