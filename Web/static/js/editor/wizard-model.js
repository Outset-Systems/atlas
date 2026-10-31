/* What guided setup can work out from a list of addresses, with no DOM.

   Every place belongs to a network, so a scan or an import on an empty Atlas
   has nowhere to land until one exists. Rather than ask for networks first,
   read them off the devices: group the IPv4 addresses by /24 and offer each
   group that no charted network already covers. A /24 is a guess, and the
   person sees it and can change it before anything is written. */

const octets = (ip) => {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(String(ip ?? '').trim());
  if (!m) return null;
  const parts = m.slice(1).map(Number);
  return parts.every((n) => n <= 255) ? parts : null;
};
const toInt = (p) => ((p[0] * 16777216) + (p[1] << 16) + (p[2] << 8) + p[3]);

/** Is this IPv4 address inside `cidr`? Anything unparsable is simply no. */
export function inCidr(ip, cidr) {
  const addr = octets(ip);
  const [base, bits] = String(cidr ?? '').trim().split('/');
  const net = octets(base);
  const len = Number(bits);
  if (!addr || !net || !Number.isInteger(len) || len < 0 || len > 32) return false;
  const size = 2 ** (32 - len);
  return Math.floor(toInt(addr) / size) === Math.floor(toInt(net) / size);
}

/** The /24s these addresses sit on that no network in `zones` covers, busiest
    first: `{ id, name, subnet, count }`. */
export function suggestNetworks(ips, zones = []) {
  const found = new Map();
  for (const ip of ips || []) {
    const p = octets(ip);
    if (!p || zones.some((z) => inCidr(ip, z.subnet))) continue;
    const key = `${p[0]}.${p[1]}.${p[2]}`;
    found.set(key, (found.get(key) || 0) + 1);
  }
  return [...found].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], undefined, { numeric: true }))
    .map(([key, count]) => ({
      id: `net-${key.replaceAll('.', '-')}`,
      name: `Network ${key}.x`,
      subnet: `${key}.0/24`,
      count,
    }));
}
