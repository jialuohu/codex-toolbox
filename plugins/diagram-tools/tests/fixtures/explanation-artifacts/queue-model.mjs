// Synthetic, non-preemptive single-server FIFO example; all times are seconds.
export function schedule(jobs) {
  let available = 0;
  let previousArrival = 0;
  const ids = new Set();
  return jobs.map((job) => {
    if (typeof job.id !== 'string' || !job.id || ids.has(job.id)
        || !Number.isFinite(job.arrival) || !Number.isFinite(job.service)
        || job.arrival < previousArrival || job.service < 0) {
      throw new Error('Jobs require unique IDs and ordered nonnegative finite times');
    }
    ids.add(job.id);
    previousArrival = job.arrival;
    const start = Math.max(available, job.arrival);
    const finish = start + job.service;
    available = finish;
    return { id: job.id, start, finish, wait: start - job.arrival };
  });
}
