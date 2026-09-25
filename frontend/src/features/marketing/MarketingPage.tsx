import { Nav } from "./Nav";
import { Hero } from "./Hero";
import { Benefits } from "./Benefits";
import { Pricing } from "./Pricing";
import { Footer } from "./Footer";

export default function MarketingPage() {
  return (
    <div className="flex-1">
      <Nav />
      <main>
        <Hero />
        <Benefits />
        <Pricing />
      </main>
      <Footer />
    </div>
  );
}
